import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAM_MED3D_DIR = os.path.join(BASE_DIR, "frame", "SAM-Med3D-main")
SAM_CKPT = os.path.join(SAM_MED3D_DIR, "ckpt", "sam_med3d_turbo.pth")
TEMP_DIR = os.path.join(BASE_DIR, "temp", "segmentation")
os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_HU_WINDOW = (100, 700)
DEFAULT_TARGET_SPACING = (0.6, 0.6, 0.6)
DEFAULT_MIN_COMPONENT_SIZE = 500
DEFAULT_CLOSING_KERNEL = 3
DEFAULT_NUM_CLICKS = 2
DEFAULT_THRESHOLD = 0.3
