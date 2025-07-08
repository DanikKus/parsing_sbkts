import pytesseract
from PIL import Image
from utils.parse_fields_ocr import parse_fields


def extract_text_from_images(image_paths):
    full_text = ""
    for path in image_paths:
        text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
        print(f"📷 Распознанный текст с {path}:\n{text}\n{'='*60}")
        full_text += text + "\n"
    return full_text
