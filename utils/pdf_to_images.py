from pdf2image import convert_from_path
import os

def convert_pdf_to_images(pdf_path, output_folder):
    images = convert_from_path(pdf_path, dpi=300)
    image_paths = []

    for i, img in enumerate(images):
        filename = os.path.join(output_folder, f"page_{i + 1}.jpg")
        img.save(filename, "JPEG")
        image_paths.append(filename)

    return image_paths
