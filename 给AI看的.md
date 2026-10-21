请你操作目标电脑

CH9329_CLI.py:
    用于通过串口与CH9329芯片通信
    使用python3 CH9329_CLI.py --help看帮助
    设备请自己找, 因为会变

capture.py:
    用于捕获摄像头画面
    使用python3 capture.py [camera_id]
    camera_id请自己找, 因为会变
    捕获到的图片会保存到 "./out_img" 目录下
    不用你手动删除, 每次运行都会自动删除超过1分钟的旧图片