from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Chats"

# Заголовки
ws.append(["chat_id", "message"])

# Примеры чатов (заменишь потом на свои)
ws.append([2000000001, "Привет! Это тестовое сообщение от бота."])
ws.append([2000000002, "Привет! Это тестовое сообщение от бота."])
ws.append([2000000003, "Привет! Это тестовое сообщение от бота."])

wb.save("chats.xlsx")
print("✅ Файл chats.xlsx успешно создан!")
