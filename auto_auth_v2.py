import vk_api
import json
import time
import requests
import os

def auth_account(phone, password, index):
    """Авторизация с скачиванием капчи"""
    
    def captcha_handler(captcha_img):
        captcha_url = captcha_img.get_url()
        captcha_file = f"captcha_{index}.png"
        
        print(f"\n" + "="*60)
        print("🔒 VK ТРЕБУЕТ КАПЧУ!")
        print("="*60)
        print(f"\n📥 Скачиваю капчу...")
        
        try:
            # Скачиваем капчу
            response = requests.get(captcha_url)
            with open(captcha_file, 'wb') as f:
                f.write(response.content)
            
            print(f"✅ Капча сохранена в файл: {captcha_file}")
            print(f"\n🖼️ Открой файл {captcha_file} на сервере и введи код")
            print(f"Или перейди по ссылке: {captcha_url}")
            
            key = input("\nВведи код с капчи: ").strip()
            
            # Удаляем файл
            if os.path.exists(captcha_file):
                os.remove(captcha_file)
            
            return key
            
        except Exception as e:
            print(f" Ошибка загрузки капчи: {e}")
            print(f"Попробуй открыть ссылку: {captcha_url}")
            return input("Введи код с капчи: ").strip()
    
    def two_factor_handler():
        print(f"\n🔐 VK требует 2FA код!")
        code = input("Введи код из СМС/приложения: ").strip()
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
        print(f"❌ Ошибка авторизации: {e}")
        return None

# Читаем учётные данные
credentials = []
with open('credentials.txt', 'r') as f:
    for line in f:
        line = line.strip()
        if line and ':' in line:
            phone, password = line.split(':', 1)
            if not phone.startswith('+'):
                phone = '+' + phone
            credentials.append({'phone': phone, 'password': password})

print(f" Загружено {len(credentials)} учётных записей\n")

# Загружаем config
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

accounts = config['vk_accounts']

print("="*60)
print(" АВТОМАТИЧЕСКАЯ АВТОРИЗАЦИЯ VK v2")
print("="*60)
print("Скрипт будет:")
print("1. Авторизовывать каждый аккаунт")
print("2. Скачивать капчу в файл (если нужна)")
print("3. Сохранять новые токены")
print("="*60)

success_count = 0
error_count = 0

for i, (acc, cred) in enumerate(zip(accounts, credentials)):
    print(f"\n{'='*60}")
    print(f"АККАУНТ {i+1}/{len(accounts)} (ID: {acc['user_id']})")
    print(f" Телефон: {cred['phone']}")
    print(f"{'='*60}")
    
    # Пропускаем первые 5 аккаунтов (они уже работают)
    if i < 5:
        print("⏭️  Уже авторизован (пропускаем)")
        success_count += 1
        continue
    
    print(" Авторизация...")
    token = auth_account(cred['phone'], cred['password'], i+1)
    
    if token:
        acc['token'] = token
        acc['enabled'] = True
        
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ УСПЕХ!")
        print(f"Токен: {token[:60]}...")
        success_count += 1
    else:
        print(f"\n❌ НЕ УДАЛОСЬ")
        error_count += 1
    
    time.sleep(5)

print("\n" + "="*60)
print(f"📊 ИТОГИ:")
print(f"✅ Успешно: {success_count}")
print(f"❌ Ошибки: {error_count}")
print(f"📈 Всего рабочих: {sum(1 for a in config['vk_accounts'] if a.get('enabled'))}")
print("="*60)
