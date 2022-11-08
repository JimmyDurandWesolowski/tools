#!/usr/bin/python3

'''
Lightweight background changer, using pictures from Reddit subreddit
channels, using by default "nitrogen" to change the background, and xrandr to
get multihead information.

This runs subprocesses (nitrogen and xrandr), so use with care. The benefit is
it does not require external packages (but uses a lot of Python libraries...).

Inspired from:

https://www.reddit.com/r/linux/comments/dhjxc/
  python_script_to_randomly_set_background_image/
Script to randomly set background from wallpapers subreddit. Schedule with cron.
Run "crontab -e" then add an entry such as "*/5 * * * * /home/jake/wscript.py"
Contributions are welcome. Do what ever you want with this script, but I am
not responsible for it.
'''

import argparse
import collections
import datetime
import http
import logging
import os
import pprint
import random
import re
import subprocess
import sys
import tempfile
import time
from typing import List, Optional, Union, ValuesView

import requests


class RedditPost:
    '''Reddit post class to ease the handling of Reddit posts'''
    attrs = ['author', 'created', 'name', 'permalink', 'title', 'url']
    __slots__ = attrs + ['_data', 'ext']
    IMG_EXTS = ['jpg','png']

    class UnknownPost(Exception):
        '''Reddit unknown post type specific error'''

    def __init__(self, data):
        self.author: str
        self.created: str
        self.name: str
        self.permalink: str
        self.title: str
        self.url: str
        if data['kind'] != 't3':
            raise self.UnknownPost(f'Unknown post {data["kind"]}')
        for attr in self.__slots__:
            setattr(self, attr, data[attr])
        try:
            _, self.ext = self.url.rsplit('.', 1)
        except ValueError:
            self.ext = None

    def __str__(self):
        return self.title

    def is_image(self):
        '''Returns true if the post is an image'''
        if self.ext not in self.IMG_EXTS:
            return False
        return True

    def download_imig(self, img_dest):
        '''Download the image from the post'''
        resp = requests.get(self.url)
        resp.raise_for_status()
        with open(img_dest, 'wb') as dest_fp:
            dest_fp.write(resp.content)
        return dest

    def download_meta(self, meta_dest):
        '''Download the metadata from the post'''
        with open(meta_dest, 'wt', encoding='utf-8') as dest_fp:
            dest_fp.write(pprint.pformat(
                {attr: getattr(self, attr) for attr in self.attrs}, indent=2))


class Displays(collections.UserDict):
    '''
    Xrandr display representation class
    Store display information as a dictionary with
    {
        display_name1: Display(display_num1, display_name1),
        display_name2: Display(display_num2, display_name2),
        ...
    }
    '''
    REGEX = re.compile(r'\s*(?P<num>\d+).+\s(?P<name>\S+)')

    class Display(collections.namedtuple('Display', ['num', 'name'])):
        '''Xrandr display representation'''
        def __str__(self):
            return f'Display {self.num}: {self.name}'

    class Error(Exception):
        '''Display specific error'''

    def __init__(self, **data):
        cmd = ['xrandr', '--listactivemonitors']
        try:
            cmd_output = subprocess.check_output(cmd)
        except subprocess.CalledProcessError as exc:
            raise Displays.Error(
                'Failed to run "{" ".join(cmd)}": {exc}') from exc
        for match in self.REGEX.finditer(cmd_output.decode()):
            info = match.groupdict()
            data[info['name']] = self.Display(int(info['num']), info['name'])
        if not data:
            raise Displays.Error('Failed to find display information')
        super().__init__(**data)

    def get_name(self, num):
        '''Get the display name associated with the number "num"'''
        for display_elt in self.values():
            if display_elt.num == num:
                return display_elt
        raise KeyError(num)

    def type_helper(self, value):
        '''
        Returns a Display based if the value represents an existing display,
        either using its number or name. It can be used in association with
        "argparse.ArgumentParser.add_argument" "type" keyword.
        Raises ValueError if the value cannot be matched to a display.
        '''
        try:
            num = int(value)
        except ValueError:
            try:
                return self[value]
            except KeyError as key_error:
                raise ValueError from key_error
        try:
            return self.get_name(num)
        except KeyError as key_num_error:
            raise ValueError from key_num_error


class BackgroundChanger:
    '''
    Main class responsible for loading, downloading, and updating the
    background of the display(s)
    '''
    BACKGROUND_CHANGING_TOOL = 'nitrogen --set-zoom-fill'
    USER_AGENT = 'BG changer 0.1'
    REDDIT_JSON_TEMPLATE = 'http://www.reddit.com/r/{}/top/.json'

    def __init__(self, subreddits,
                 display: Optional[List[Displays.Display]] = None,
                 loglevel=0):
        logging.basicConfig(format='%(name)s: %(message)s')
        self.logger = logging.getLogger('BackgroundChanger')
        self.displays: Union[List[Displays.Display],
                             ValuesView[Displays.Display]]
        if display is None:
            self.displays = Displays().values()
        else:
            self.displays = display
        self.selected: List[RedditPost] = []
        self.subreddits = subreddits

        if loglevel:
            if loglevel == 1:
                logging.getLogger().setLevel(logging.INFO)
                self.logger.setLevel(logging.INFO)
            elif loglevel >= 2:
                logging.getLogger().setLevel(logging.DEBUG)
                self.logger.setLevel(logging.DEBUG)
        self.logger.info('Updating background from subreddit(s) "%s" on "%s"',
                         ', '.join(self.subreddits),
                         ', '.join(str(display) for display in self.displays))

    def _subreddit_load(self, subreddit) -> List[RedditPost]:
        resp = requests.get(self.REDDIT_JSON_TEMPLATE.format(subreddit),
                            headers={'User-agent': self.USER_AGENT})
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if ((exc.response.status_code ==
                 http.HTTPStatus.TOO_MANY_REQUESTS)):
                self.logger.warning(
                    'Too many requests sent, waiting 1 min')
                time.sleep(60)
                return []
            raise exc
        json_obj = resp.json()
        try:
            posts = [RedditPost(post) for post in json_obj['data']['children']]
        except KeyError as key_err:
            self.logger.error('Could not find %s in the JSON response, exiting',
                              key_err)
            return []
        self.logger.info('%d total posts found', len(posts))
        return posts

    def load(self):
        '''
        Load Reddit posts for the subreddits, and randomly selects as many as
        the number of displays to update
        '''
        for subreddit in self.subreddits:
            for attempt in range(1, 4, 1):
                self.logger.info('Attempt %d to load %s', attempt, subreddit)
                try:
                    posts = self._subreddit_load(subreddit)
                    if posts:
                        break
                except requests.HTTPError as exc:
                    self.logger.warning('Failed to load "%s": %s',
                                        subreddit, exc)
                    break
        posts_image = [post for post in posts if post.is_image()]
        if not posts_image:
            self.logger.error('No post with image found')
            return None
        self.selected = random.choices(posts_image, k=len(self.displays))
        return self.selected

    def update(self, directory, meta=False):
        '''
        Update the backgroup of the display(s). Load the posts if not
        previously done
        '''
        if not self.selected:
            self.load()
        date = datetime.datetime.now().strftime('%Y%m%d-%H%M')
        for disp, post in zip(self.displays, self.selected):
            self.logger.info('Using post "%s" for display %s', post, disp)
            if meta:
                post.download_meta(os.path.join(directory,
                                                f'{date}-{disp.num}-meta.txt'))
            dest_img = os.path.join(directory,
                                    f'{date}-{disp.num}background-.{post.ext}')
            post.download_imig(dest_img)
            cmd = (self.BACKGROUND_CHANGING_TOOL.split(' ')
                   + [f'--head={disp.num}', dest_img])
            self.logger.debug('Running "%s"', cmd)
            subprocess.check_call(cmd)


if __name__ == '__main__':
    curdir = os.path.dirname(os.path.realpath(sys.argv[0]))
    output = os.path.join(curdir, 'background')
    try:
        displays = Displays()
    except Displays.Error as display_error:
        print(display_error)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='Lightweight background changer',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-M', '--no-metadata', action='store_true',
                        help='disable image source information saving')
    parser.add_argument('-d', '--display', type=displays.type_helper,
                        nargs='*', help='display to update',
                        default=displays.values())
    parser.add_argument('-l', '--list-displays', action='store_true',
                        help='list displays')
    parser.add_argument('-s', '--subreddits', nargs='*', default=['EarthPorn'],
                        help='subreddits to downloads pictures from')
    group_saving = parser.add_mutually_exclusive_group()
    group_saving.add_argument('--dest', default=output,
                              help='directory to save the picture in')
    group_saving.add_argument('-t', '--temporary', action='store_true',
                              help='do not save the pictures permanently')
    parser.add_argument('-T', '--tool', help='user this tool to change the '
                        'background',
                        default=BackgroundChanger.BACKGROUND_CHANGING_TOOL)
    parser.add_argument('-v', '--verbosity', action='count',
                        help='increase verbosity')

    args = parser.parse_args()
    if args.list_displays:
        print('Display(s):')
        for display_opt in displays.values():
            print(f'  {display_opt}')
        sys.exit(0)

    bgc = BackgroundChanger(args.subreddits, display=args.display,
                            loglevel=args.verbosity)

    if args.temporary:
        with tempfile.TemporaryDirectory() as dest:
            if not bgc.load():
                sys.exit(1)
            bgc.update(dest, meta=False)
    else:
        os.makedirs(args.dest, exist_ok=True)
        if not bgc.load():
            sys.exit(1)
        bgc.update(args.dest, meta=not args.no_metadata)
