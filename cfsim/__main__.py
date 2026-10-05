"""Run an unchanged cflib script in the simulator:

    python -m cfsim my_script.py
    python -m cfsim --world maze --model brushless my_script.py
    python -m cfsim --viewer browser my_script.py
    python -m cfsim --list-worlds
    python -m cfsim --editor          make a world from a floor plan (in the browser)
"""
import argparse
import os
import runpy
import sys

import cfsim


def main():
    p = argparse.ArgumentParser(
        prog='python -m cfsim',
        description='Run a Crazyflie (cflib) script in the cfsim simulator.')
    p.add_argument('script', nargs='?', help='the Python script to run')
    p.add_argument('args', nargs=argparse.REMAINDER, help='arguments for the script')
    p.add_argument('--world', default='room',
                   help="room, corridor, maze, obstacles, arena, open, or a .txt map file")
    p.add_argument('--model', default='2.1+', help="'2.1+' or 'brushless'")
    p.add_argument('--positioning', default='flow', choices=['flow', 'lighthouse', 'none'])
    p.add_argument('--no-noise', action='store_true', help='perfect sensors, no drift')
    p.add_argument('--decks', default='flow,multiranger',
                   help="mounted decks, comma separated (default: flow,multiranger)")
    p.add_argument('--viewer', choices=['window', 'browser', 'none'], default='window',
                   help='where to show the live 3D view (default: window)')
    p.add_argument('--no-viewer', action='store_true', help='no live 3D view (= --viewer none)')
    p.add_argument('--port', type=int, default=8765,
                   help='first port tried for --viewer browser and --editor (default 8765)')
    p.add_argument('--battery-drain', type=float, default=1.0,
                   help='battery drains this many times faster (default 1)')
    p.add_argument('--list-worlds', action='store_true', help='show the built-in worlds')
    p.add_argument('--editor', action='store_true',
                   help='open the room editor: make a world from a floor plan image')
    a = p.parse_args()

    if a.editor:
        from cfsim.web import run_editor
        run_editor(a.port)
        return
    if a.list_worlds:
        print('Built-in worlds:', ', '.join(cfsim.worlds()))
        return
    if not a.script:
        p.print_help()
        return
    if not os.path.isfile(a.script):
        sys.exit(f'Script not found: {a.script}')

    cfsim.enable(world=a.world, model=a.model, positioning=a.positioning,
                 noise=not a.no_noise, decks=a.decks,
                 viewer='none' if a.no_viewer else a.viewer, port=a.port,
                 battery_drain=a.battery_drain)
    sys.argv = [a.script] + a.args
    script_dir = os.path.dirname(os.path.abspath(a.script))
    sys.path.insert(0, script_dir)
    runpy.run_path(a.script, run_name='__main__')


if __name__ == '__main__':
    main()
