#!/usr/bin/env python3
import tempfile
import time
import cv2
import sys
import os

out_dir = "./out_img"
ext = ".png"
os.makedirs(out_dir, exist_ok=True)

img_expire = 60 # 1分钟

def auto_expire():
    for file in os.listdir(out_dir):
        if not file.endswith(ext):
            continue
        path = os.path.join(out_dir, file)
        if os.path.getmtime(path) + img_expire < time.time():
            print(f"过期: {path}")
            os.remove(path)

def run(camera_id):
    # 打开摄像头
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print(f"无法打开摄像头 {camera_id}", file=sys.stderr)

    ret, frame = cap.read()
    if not ret:
        print("读取摄像头画面失败", file=sys.stderr)

    fd, path = tempfile.mkstemp(suffix=ext, dir=out_dir)
    os.close(fd)
    try:
        cv2.imwrite(path, frame)
    except Exception as e:
        os.remove(path)
        raise e
    print(os.path.relpath(path, os.getcwd()))


if __name__ == "__main__":
    auto_expire()
    argc = len(sys.argv)
    if argc == 1:
        run(0)
    else:
        if not sys.argv[1].isdigit():
            print("参数必须是整数", file=sys.stderr)
            exit(1)
        run(int(sys.argv[1]))