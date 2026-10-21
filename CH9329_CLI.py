#!/usr/bin/env python3
"""CH9329 keyboard/mouse control through a Linux CH340 serial adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import serial


class HID:
    def __init__(self, port, baud):
        self.serial = serial.Serial(port, baud, timeout=0.7,
                                    write_timeout=1, exclusive=True)
        self.serial.reset_input_buffer()
        port_id = hashlib.sha256(str(port).encode()).hexdigest()[:16]
        self.position_file = Path.cwd() / ('ch9329-position-' + port_id + '.json')
        self.position = None
        try:
            position = json.loads(self.position_file.read_text())
            if (isinstance(position, list) and len(position) == 2 and
                    all(isinstance(v, int) and 0 <= v <= 4095 for v in position)):
                self.position = tuple(position)
        except (OSError, ValueError):
            pass

    def close(self):
        self.serial.close()

    def exchange(self, command, payload=b''):
        frame = bytes([0x57, 0xAB, 0, command, len(payload)]) + payload
        self.serial.write(frame + bytes([sum(frame) & 255]))
        self.serial.flush()
        head = self.serial.read(5)
        if len(head) != 5 or head[:3] != b'\x57\xab\x00' or head[4] > 64:
            raise RuntimeError('Invalid/missing response header: ' + head.hex(' '))
        tail = self.serial.read(head[4] + 1)
        if len(tail) != head[4] + 1:
            raise RuntimeError('Incomplete response')
        if (sum(head + tail[:-1]) & 255) != tail[-1]:
            raise RuntimeError('Response checksum mismatch')
        data = tail[:-1]
        if head[3] != command | 0x80:
            raise RuntimeError('CH9329 error response: ' + (head + tail).hex(' '))
        if command in (2, 4, 5) and data != b'\x00':
            raise RuntimeError('HID command failed: ' + data.hex(' '))
        return data

    def info(self):
        data = self.exchange(1)
        if len(data) != 8:
            raise RuntimeError('Invalid device info length')
        return {'version_raw': hex(data[0]), 'usb_enumerated': data[1] == 1,
                'caps_lock': bool(data[2] & 2), 'leds_raw': hex(data[2])}

    def key(self, usage, modifier=0):
        try:
            self.exchange(2, bytes([modifier, 0, usage, 0, 0, 0, 0, 0]))
            time.sleep(0.06)
        finally:
            self.exchange(2, bytes(8))
        time.sleep(0.08)

    def relative(self, dx, dy):
        # Relative input can be accelerated by the target OS, so the saved
        # absolute position is no longer reliable.
        self.forget_position()
        previous_x = previous_y = 0
        started = time.monotonic()
        for step in range(1, 9):
            self.wait_until(started + 0.2 * step / 8)
            x, y = round(dx * step / 8), round(dy * step / 8)
            if (x, y) != (previous_x, previous_y):
                self.exchange(5, bytes([1, 0, (x - previous_x) & 255,
                                        (y - previous_y) & 255, 0]))
            previous_x, previous_y = x, y

    @staticmethod
    def wait_until(deadline):
        time.sleep(max(0, deadline - time.monotonic()))

    def forget_position(self):
        self.position = None
        self.position_file.unlink(missing_ok=True)

    def absolute(self, x, y, width, height, click=False, button='left',
                 from_x=None, from_y=None):
        hx = min(4095, round(x / width * 4096))
        hy = min(4095, round(y / height * 4096))
        if from_x is not None and from_y is not None:
            start = (min(4095, round(from_x / width * 4096)),
                     min(4095, round(from_y / height * 4096)))
        else:
            start = self.position
        def report(px, py, buttons=0):
            return bytes([2, buttons, px & 255, px >> 8, py & 255, py >> 8, 0])

        # Discard stale state before sending: interrupted movement must not
        # leave the next invocation believing it reached the destination.
        self.forget_position()
        if start is None:
            self.exchange(4, report(hx, hy))
        else:
            started = time.monotonic()
            for step in range(1, 9):
                self.wait_until(started + 0.2 * step / 8)
                px = round(start[0] + (hx - start[0]) * step / 8)
                py = round(start[1] + (hy - start[1]) * step / 8)
                self.exchange(4, report(px, py))
        self.position_file.write_text(json.dumps([hx, hy]))
        self.position = (hx, hy)
        if click:
            time.sleep(0.12)
            try:
                self.exchange(4, report(hx, hy, {'left': 1, 'right': 2}[button]))
                time.sleep(0.09)
            finally:
                self.exchange(4, report(hx, hy))


def character_key(char, caps):
    if char.isascii() and char.isalpha():
        return ord(char.lower()) - ord('a') + 4, 2 if char.isupper() != caps else 0
    if char in '1234567890':
        return 0x1E + '1234567890'.index(char), 0
    plain = {' ': 0x2C, '-': 0x2D, '=': 0x2E, '[': 0x2F, ']': 0x30,
             '\\': 0x31, ';': 0x33, "'": 0x34, '`': 0x35, ',': 0x36,
             '.': 0x37, '/': 0x38}
    shifted = dict(zip('!@#$%^&*()', range(0x1E, 0x28)))
    shifted.update({'_': 0x2D, '+': 0x2E, '{': 0x2F, '}': 0x30,
                    '|': 0x31, ':': 0x33, '"': 0x34, '~': 0x35,
                    '<': 0x36, '>': 0x37, '?': 0x38})
    if char in plain:
        return plain[char], 0
    if char in shifted:
        return shifted[char], 2
    raise ValueError('Unsupported character; use printable US-layout ASCII: ' + repr(char))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--baud', type=int, default=9600)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('info')
    text = commands.add_parser('text')
    text.add_argument('value')
    key = commands.add_parser('key')
    key.add_argument('name', choices=['enter', 'escape', 'tab', 'space', 'backspace',
                                    'cmd-space', 'ctrl-space'])
    move = commands.add_parser('move')
    move.add_argument('dx', type=int)
    move.add_argument('dy', type=int)
    for name in ('point', 'click', 'right-click'):
        command = commands.add_parser(name)
        command.add_argument('x', type=int)
        command.add_argument('y', type=int)
        command.add_argument('--width', type=int, required=True)
        command.add_argument('--height', type=int, required=True)
        command.add_argument('--from-x', type=int,
                             help='Starting cursor X; overrides the saved position')
        command.add_argument('--from-y', type=int,
                             help='Current cursor Y; use with --from-x')
        if name == 'click':
            command.add_argument('--button', choices=['left', 'right'], default='left')
    args = parser.parse_args()
    if args.command == 'move' and not (-127 <= args.dx <= 127 and -127 <= args.dy <= 127):
        parser.error('Relative movement must be between -127 and 127 per axis')
    if args.command in ('point', 'click', 'right-click'):
        if not (args.width > 0 and args.height > 0 and
                0 <= args.x < args.width and 0 <= args.y < args.height):
            parser.error('Coordinates must be inside the supplied display dimensions')
        if (args.from_x is None) != (args.from_y is None):
            parser.error('--from-x and --from-y must be supplied together')
        if args.from_x is not None and not (0 <= args.from_x < args.width and
                                            0 <= args.from_y < args.height):
            parser.error('Starting coordinates must be inside the display dimensions')
    if args.command == 'text':
        # Validate the entire string before sending anything.
        for char in args.value:
            character_key(char, False)
    device = HID(args.port, args.baud)
    try:
        info = device.info()
        if args.command == 'info':
            print(json.dumps(info, ensure_ascii=False))
            return
        if not info['usb_enumerated']:
            raise RuntimeError('Target USB not enumerated; no input sent')
        if args.command == 'text':
            device.exchange(2, bytes(8))
            for char in args.value:
                device.key(*character_key(char, info['caps_lock']))
        elif args.command == 'key':
            keys = {'enter': (0x28, 0), 'escape': (0x29, 0), 'tab': (0x2B, 0),
                    'space': (0x2C, 0), 'backspace': (0x2A, 0),
                    'cmd-space': (0x2C, 8), 'ctrl-space': (0x2C, 1)}
            device.key(*keys[args.name])
        elif args.command == 'move':
            device.relative(args.dx, args.dy)
        else:
            device.absolute(args.x, args.y, args.width, args.height,
                            click=args.command in ('click', 'right-click'),
                            button=('right' if args.command == 'right-click' else
                                    getattr(args, 'button', 'left')),
                            from_x=args.from_x, from_y=args.from_y)
        print('OK: command acknowledged by CH9329')
    finally:
        device.close()


if __name__ == '__main__':
    main()
