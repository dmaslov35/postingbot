import json

# Номера телефонов
phones = [
    "89235866030",
    "89237006030",
    "89134451012",
    "89134451215",
    "89394899905",
    "89913760109",
    "89956045033"
]

# Загружаем config.json
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Добавляем телефоны к аккаунтам (циклически)
accounts = config['vk_accounts']
for i, acc in enumerate(accounts):
    phone_index = i % len(phones)
    acc['phone'] = phones[phone_index]
    print(f"✅ Аккаунт {acc['user_id']}: +{phones[phone_index]}")

# Сохраняем обратно
with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"\n✅ Готово! Добавлены телефоны ко всем {len(accounts)} аккаунтам.")
