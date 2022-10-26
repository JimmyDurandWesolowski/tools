#! /usr/bin/env python

'''
Simple script to try to draw the "perfect" circle, such as the one to draw on
https://vole.wtf/perfect-circle/
'''



import argparse
import collections
import math
import os
import re
import shutil
import subprocess
import sys
import time
from typing import List

try:
    # python-libxdo package, _not_ the xdo package!
    import xdo  # type: ignore
    XDO_LIB = True
except ImportError:
    xdo = None
    XDO_LIB = False


REGEX_MOSELOC = re.compile(r'x:([0-9]+) y:([0-9]+).*')
TOOLNAME = 'xdotool'


def float_positive(value):
    '''Check that value is a positive float number'''
    conv = float(value)
    if conv < 0:
        raise argparse.ArgumentTypeError(f'{value} is negative')
    return conv

class CircleDrawer:
    '''
    Monkey typing, changing the function depending on XDO_LIB is an option, but
    for sake of readability, a condition is used in the function, and a call to
    the appropriate function is made.
    '''
    class RequirementError(Exception):
        '''CircleDrawer expected prerequisite specific error'''

    class ExecutionError(Exception):
        '''CircleDrawer execution error'''

    Coord = collections.namedtuple('Coord', ['x', 'y'])

    def __init__(self):
        self.coordinates = []
        self.toolpath = None
        self.xdo = None

        if XDO_LIB:
            self.xdo = xdo.Xdo()
            return
        self.toolpath = shutil.which(TOOLNAME)

        if self.toolpath is not None:
            return
        raise CircleDrawer.RequirementError(
            f'{TOOLNAME} missing, please install its package '
            'or install the python-libxdo Python package')

    def _draw_lib(self, sleep: float, mouse_press: bool = True):
        if mouse_press:
            self.xdo.mouse_down(xdo.CURRENTWINDOW, xdo.MOUSE_LEFT)
        for coord in self.coordinates:
            self.xdo.wait_for_mouse_move_to(coord.x, coord.y)
        if mouse_press:
            self.xdo.mouse_up(xdo.CURRENTWINDOW, xdo.MOUSE_LEFT)

    def _draw_tool(self, sleep: float, mouse_press: bool = True):
        cmds = [f'mousemove {coord.x} {coord.y} sleep {sleep}'
                for coord in self.coordinates]
        if mouse_press:
            cmds = [cmds[0], 'mousedown 1'] + cmds[1:] + ['mouseup 1']
        self._tool_run(cmds)

    def _mouse_location_tool(self):
        output = self._tool_run(['getmouselocation'])
        match = REGEX_MOSELOC.match(output)
        if match is None:
            raise CircleDrawer.ExecutionError(
                f'Failed to get mouse current location from "{output}"')
        vals = (int(val) for val in match.groups())
        return CircleDrawer.Coord(*vals)

    def _mouse_location_lib(self) -> 'CircleDrawer.Coord':
        loc = self.xdo.get_mouse_location()
        return CircleDrawer.Coord(loc.x, loc.y)

    def _tool_run(self, commands: List[str]):
        cmds_str = ''.join([f'{cmd}{os.linesep}' for cmd in commands]).encode()
        try:
            with subprocess.Popen([self.toolpath, '-'],
                                  stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) as proc:
                stdout, _ = proc.communicate(cmds_str)
        except subprocess.CalledProcessError as call_exc:
            raise CircleDrawer.ExecutionError(call_exc)
        return stdout.decode()

    def compute(self, start: 'CircleDrawer.Coord',
                radius: int, point_nb: int, tweak: int) -> None:
        '''
        Compute the circle coordinates, starting from the "start" ones,
        with the given "radius" and point numbers "point_nb".
        "tweak" allows adding more points to the circle to redraw part
        of it.
        Note: one number is first deducted to the number of points to account
        for the last point being the same as the first to complete the loop.
        '''
        circle_slice = 2 * math.pi / (point_nb - 1)
        point_nb += tweak
        self.coordinates = [
            CircleDrawer.Coord(
                int(start.x + radius * math.cos(point * circle_slice)),
                int(start.y + radius * math.sin(point * circle_slice)))
            for point in range(point_nb + 1)
        ]

    def draw(self, sleep: float, mouse_press: bool) -> None:
        '''draw the circle with the mouse, sleeping "sleep" seconds between
        each movement
        '''
        if XDO_LIB:
            self._draw_lib(sleep, mouse_press)
            return
        self._draw_tool(sleep, mouse_press)

    def mouse_location(self) -> 'CircleDrawer.Coord':
        '''Get the current mouse location on the screen as a
        CircleDrawer.Coord.
        '''
        if XDO_LIB:
            return self._mouse_location_lib()
        return self._mouse_location_tool()


if __name__ == '__main__':
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

    try:
        circle_drawer = CircleDrawer()
    except CircleDrawer.RequirementError as exc:
        print(exc)
        sys.exit(1)

    if args.wait and not args.dump:
        time.sleep(args.wait - args.sleep)

    try:
        pos = circle_drawer.mouse_location()
        circle_drawer.compute(pos,
                              radius=args.radius,
                              point_nb=args.point_nb,
                              tweak=args.tweak)
        if args.dump:
            print(circle_drawer.coordinates)
            sys.exit(0)
        circle_drawer.draw(args.sleep, args.mouse_press)
    except CircleDrawer.ExecutionError as exc:
        print(exc)
        sys.exit(2)
