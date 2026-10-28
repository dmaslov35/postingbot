import vk_api
import json
import time

def auth_with_captcha_and_2fa(phone, password):
    """Авторизация с обработкой капчи и 2FA"""
    
    def captcha_handler(captcha_img):
        print(f"\n VK требует капчу!")
        print(f"📸 Открой ссылку: {captcha_img.get_url()}")
        key = input("Введи код с капчи: ").strip()
        return key
    
    def two_factor_handler():
        print(f"\n🔐 VK требует код из приложения/СМС!")
        code = input("Введи 2FA код: ").strip()
        return code
    
    try:
        vk_session = vk_api.VkApi(
            phone, 
            password,
            app_id=51552703,
            captcha_handler=captcha_handler,
            auth_handler=two_factor_handler
        )
        
        vk_session.auth()
        return vk_session.token['access_token']
        
    except vk_api.AuthError as error_msg:
        print(f"❌ Ошибка авторизации: {error_msg}")
        return None
    except Exception as e:
        print(f"❌ Неизвестная ошибка: {e}")
        return None

# Загружаем config
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

accounts = config['vk_accounts']

print("="*60)
print(" УМНАЯ АВТОРИЗАЦИЯ VK")
print("="*60)
print("\nЭтот скрипт:")
print("1. Авторизует каждый аккаунт по логину/паролю")
print("2. Автоматически обработает капчу")
print("3. Обработает 2FA (код из приложения/СМС)")
print("4. Получит новые токены, привязанные к IP сервера")
print("5. Сохранит их в config.json")
print("\n" + "="*60)

success_count = 0
skip_count = 0
error_count = 0

for i, acc in enumerate(accounts):
    print(f"\n{'='*60}")
    print(f"АККАУНТ {i+1}/{len(accounts)} (ID: {acc['user_id']})")
    print(f"Текущий статус: {'✅ OK' if acc.get('enabled') else '❌ Отключён'}")
    print(f"{'='*60}")
    
    choice = input("Авторизовать? (y=да, Enter=пропустить): ").strip().lower()
    if choice != 'y':
        print("⏭️  Пропущено")
        skip_count += 1
        continue
    
    phone = input(" Телефон (+7...): ").strip()
    password = input("🔑 Пароль: ").strip()
    
    print("\n⏳ Авторизация...")
    token = auth_with_captcha_and_2fa(phone, password)
    
    if token:
        acc['token'] = token
        acc['enabled'] = True
        
        # Сохраняем сразу
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ УСПЕХ!")
        print(f"Токен: {token[:60]}...")
        print(f"Аккаунт {acc['user_id']} обновлён и включён")
        success_count += 1
    else:
        print(f"\n❌ НЕ УДАЛОСЬ авторизовать")
        error_count += 1
    
    time.sleep(3)

print("\n" + "="*60)
print(f"📊 ИТОГИ:")
print(f"✅ Успешно авторизовано: {success_count}")
print(f"⏭️  Пропущено: {skip_count}")
print(f"❌ Ошибки: {error_count}")
print(f"📈 Всего рабочих аккаунтов: {sum(1 for a in config['vk_accounts'] if a.get('enabled'))}")
print("="*60)
