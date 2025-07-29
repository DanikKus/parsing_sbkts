import aspose.pdf as ap

def extract_text_from_pdf(pdf_path):
    # Загружаем PDF
    print(f"📄 Парсим текст из: {pdf_path}")
    doc = ap.Document(pdf_path)

    # Создаём TextAbsorber для извлечения текста
    text_absorber = ap.text.TextAbsorber()

    # Проходимся по всем страницам и применяем TextAbsorber
    doc.pages.accept(text_absorber)

    # Получаем извлечённый текст
    extracted_text = text_absorber.text

    return extracted_text


# Сохраняем в текстовый файл
# with open("output.txt", "w", encoding="utf-8") as f:
#     f.write(extracted_text)

# print("✅ Текст успешно сохранён в output.txt")
