import qrcode

def generate_qr_code(link, output_file="qrcode.png"):
    # Создаем объект QR-кода
    qr = qrcode.QRCode(
        version=1,  # размер QR-кода (1 — минимальный)
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # уровень коррекции ошибок
        box_size=10,  # размер каждой "коробки" (пикселя)
        border=4,  # толщина рамки (в "коробках")
    )
    
    # Добавляем ссылку в QR-код
    qr.add_data(link)
    qr.make(fit=True)
    
    # Генерируем изображение QR-кода
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_file)
    print(f"QR-код успешно создан и сохранён в файле {output_file}")

if __name__ == "__main__":
    link = input("Введите ссылку для генерации QR-кода: ")
    generate_qr_code(link)
