import vk_api
import json
import time

# Загружаем config
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

accounts = config['vk_accounts']

print("📝 Авторизация аккаунтов по логину/паролю\n")
print("⚠️  ВНИМАНИЕ: Для каждого аккаунта нужно ввести:")
print("- Номер телефона (в формате +79991234567)")
print("- Пароль\n")

for i, acc in enumerate(accounts):
    print(f"\n--- Аккаунт {i+1}/{len(accounts)} (ID: {acc['user_id']}) ---")
    
    phone = input("Телефон (+7...): ").strip()
    password = input("Пароль: ").strip()
    
    try:
        vk_session = vk_api.VkApi(
            phone, 
            password,
            app_id=51552703
        )
        
        vk_session.auth()
        
        new_token = vk_session.token['access_token']
        acc['token'] = new_token
        
        print(f"✅ Токен получен: {new_token[:50]}...")
        print(f"✅ Аккаунт {acc['user_id']} обновлён")
        
        # Сохраняем после каждого аккаунта
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        time.sleep(2)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print(f"️  Аккаунт пропущен")

print("\n✅ Готово!")
