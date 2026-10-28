import vk_api
import json
import time

def auth_account(phone, password):
    """Авторизация с обработкой капчи и 2FA"""
    
    def captcha_handler(captcha_img):
        print(f"\n🔒 VK требует капчу!")
        print(f"📸 Открой: {captcha_img.get_url()}")
        key = input("Введи код с капчи: ").strip()
        return key
    
    def two_factor_handler():
        print(f"\n VK требует 2FA код!")
        code = input("Введи код: ").strip()
        return code, False
    
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
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

# Читаем учётные данные
credentials = []
with open('credentials.txt', 'r') as f:
    for line in f:
        line = line.strip()
        if line and ':' in line:
            phone, password = line.split(':', 1)
            # Добавляем + к номеру
            if not phone.startswith('+'):
                phone = '+' + phone
            credentials.append({'phone': phone, 'password': password})

print(f"📋 Загружено {len(credentials)} учётных записей\n")

# Загружаем config
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

accounts = config['vk_accounts']

print("="*60)
print("🤖 АВТОМАТИЧЕСКАЯ АВТОРИЗАЦИЯ VK")
print("="*60)

success_count = 0
error_count = 0

for i, (acc, cred) in enumerate(zip(accounts, credentials)):
    print(f"\n{'='*60}")
    print(f"АККАУНТ {i+1}/{len(accounts)} (ID: {acc['user_id']})")
    print(f"Телефон: {cred['phone']}")
    print(f"{'='*60}")
    
    print("⏳ Авторизация...")
    token = auth_account(cred['phone'], cred['password'])
    
    if token:
        acc['token'] = token
        acc['enabled'] = True
        
        # Сохраняем сразу
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ УСПЕХ!")
        print(f"Токен: {token[:60]}...")
        success_count += 1
    else:
        print(f"\n❌ НЕ УДАЛОСЬ")
        error_count += 1
    
    # Пауза между авторизациями
    time.sleep(5)

print("\n" + "="*60)
print(f"📊 ИТОГИ:")
print(f"✅ Успешно: {success_count}")
print(f"❌ Ошибки: {error_count}")
print(f"📈 Всего рабочих: {sum(1 for a in config['vk_accounts'] if a.get('enabled'))}")
print("="*60)
