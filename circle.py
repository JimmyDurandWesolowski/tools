#! /usr/bin/env python

import argparse
import collections
import math
import os
import re
import shutil
import subprocess
import sys
import time


TOOLNAME = 'xdotool'
REGEX_MOSELOC = re.compile(r'x:([0-9]+) y:([0-9]+).*')


Coord = collections.namedtuple('Coord', ['x', 'y'])

def float_positive(value):
    conv = float(value)
    if conv <= 0:
        raise argparse.ArgumentTypeError(f'{value} is negative')
    return conv


def compute_pos(x_start, y_start, point_nb, radius, tweak):
    # To come back to the original position, we need one more point
    circle_slice = 2 * math.pi / (point_nb - 1)
    # Additionally, a tweak is needed to ensure the circle is complete
    # (redrawing one point more)
    point_nb += tweak
    return [
        Coord(int(x_start + radius * math.cos(point * circle_slice)),
              int(y_start + radius * math.sin(point * circle_slice)))
        for point in range(point_nb + 1)
    ]

def command_list(x_pos, y_pos, arguments):
    coordinates = compute_pos(
        x_pos, y_pos, args.point_nb, args.radius, args.tweak)
    coord = coordinates.pop(0)
    cmds = [f'mousemove {coord.x} {coord.y}']
    if args.mouse_press:
        cmds.append('mousedown 1')
    for coord in coordinates:
        cmds += [
            f'sleep {arguments.sleep}',
            f'mousemove {coord.x} {coord.y}'
        ]
    if args.mouse_press:
        cmds.append('mouseup 1')
    return cmds


if __name__ == '__main__':
    toolpath = shutil.which(TOOLNAME)
    if toolpath is None:
        print(f'{TOOLNAME} missing, please install its package',
              file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='Circle drawing with mouse input')
    parser.add_argument('-d', '--dump', action='store_true',
                        help='dump the commands only')
    parser.add_argument('-m', '--mouse-press', default=True,
                        action='store_false',
                        help='do not press the mouse button when drawing')
    parser.add_argument('-p', '--point-nb', type=int, default=1000,
                        help='number of points to compute in the circle')
    parser.add_argument('-r', '--radius', type=int, default=400,
                        help='circle radius size in pixels')
    parser.add_argument('-s', '--sleep', type=float_positive, default=0.01,
                        help='sleep time between mouse moves')
    parser.add_argument('-t', '--tweak', type=int,
                        help='allow additional points to be redrawn')
    parser.add_argument('-w', '--wait', type=float_positive, default=3,
                        help='time to wait before drawing, in seconds')
    args = parser.parse_args()

    if args.wait and not args.dump:
        time.sleep(args.wait - args.sleep)
    try:
        output = subprocess.check_output([toolpath, 'getmouselocation'])
    except subprocess.CalledProcessError as exc:
        sys.exit(1)

    match = REGEX_MOSELOC.match(output.decode())
    if match is None:
        print('Failed to get mouse current location', file=sys.stderr)
        sys.exit(1)

    xstart, ystart = (int(val) for val in match.groups())
    commands = command_list(xstart, ystart, args)
    if args.dump:
        print(commands)
        sys.exit(0)

    try:
        with subprocess.Popen([toolpath, '-'],
                              stdin=subprocess.PIPE) as proc:
            output, _ = proc.communicate(
                ''.join([f'{cmd}{os.linesep}' for cmd in commands]).encode())
    except subprocess.CalledProcessError:
        print(proc.stderr, file=sys.stderr)
        sys.exit(1)
    if output:
        print(output.decode())
