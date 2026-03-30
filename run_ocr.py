import constants
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from pytesseract import pytesseract
pytesseract.tesseract_cmd = constants.tesseract_path


#Setting file paths
filename= constants.filename
path_to_read= Path.cwd()
path_to_read= Path.joinpath(path_to_read,"Details")
path_to_read= Path.joinpath(path_to_read,filename)
path_to_read= Path.joinpath(path_to_read,"Intermediates")


# Running raw tesseract on the image as a whole
def run_tesseract():
    print("Running pytesseract (version check skipped)")
    test= cv2.imread(str(Path.joinpath(path_to_read,'Image_bin.jpg')))
    print("*"*50)
    test =cv2.bitwise_not(test,mask=None)

    
    # Hardcoded compatibility for Tesseract 3 found on system
    custom_config = r"-psm 4"
    print(f"Using hardcoded config: {custom_config}")


    try:
        te=pytesseract.image_to_string(test,config=custom_config)
    except Exception as e:
        print(f"OCR FAILED: {e}")
        te = ""
        # Fallback to direct subprocess call if pytesseract fails
        try:
             import subprocess
             cmd = [constants.tesseract_path, str(Path.joinpath(path_to_read,'Image_bin.jpg')), "stdout"] + custom_config.split()
             print(f"Trying direct command: {cmd}")
             te = subprocess.check_output(cmd).decode('utf-8')
        except Exception as e2:
             print(f"Direct command passed failed too: {e2}")

    with open(Path.joinpath(path_to_read,'output.txt'),'w', encoding='utf-8') as f:
        f.write(str(te))
