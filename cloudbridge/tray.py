import threading

try:
    from PIL import Image, ImageDraw
    import pystray
except ImportError:
    pystray = None

def create_icon() -> "pystray.Icon":
    if not pystray:
        return None

    # Create a simple icon image
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Draw a blue cloud
    draw.ellipse((16, 24, 48, 56), fill=(0, 120, 255))
    draw.ellipse((8, 32, 32, 56), fill=(0, 120, 255))
    draw.ellipse((32, 32, 56, 56), fill=(0, 120, 255))

    def on_quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("CloudBridge", None, enabled=False),
        pystray.MenuItem("Status: Active", None, enabled=False),
        pystray.MenuItem("Quit", on_quit)
    )

    return pystray.Icon("cloudbridge", image, "CloudBridge", menu)

def run_tray():
    icon = create_icon()
    if icon:
        icon.run()

def start_tray_thread():
    if pystray:
        t = threading.Thread(target=run_tray, daemon=True)
        t.start()
        return t
    else:
        print("pystray or PIL not installed, skipping tray icon.")
        return None
