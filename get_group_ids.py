import requests

# Ссылки на группы
groups = [
    'https://vk.ru/ia_proden',
    'https://vk.ru/everydey',
    'https://vk.ru/club180687259'
]

print("🔍 Получаем ID групп...\n")

for url in groups:
    # Извлекаем короткий адрес
    short_name = url.replace('https://vk.ru/', '')
    
    # Для групп с clubXXXXX
    if short_name.startswith('club'):
        group_id = -int(short_name.replace('club', ''))
        print(f"✅ {url} → ID: {group_id}")
    else:
        # Для групп с коротким адресом делаем API запрос
        try:
            # Используем токен первого аккаунта из config
            import json
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                token = config['vk_accounts'][0]['token']
            
            response = requests.get(
                'https://api.vk.com/method/groups.get',
                params={
                    'group_id': short_name,
                    'access_token': token,
                    'v': '5.199'
                }
            )
            data = response.json()
            
            if 'response' in data and 'items' in data['response']:
                group_id = -data['response']['items'][0]['id']
                print(f"✅ {url} → ID: {group_id}")
            else:
                print(f" {url} → Ошибка: {data}")
        except Exception as e:
            print(f"❌ {url} → Ошибка: {e}")

print("\n Для создания тестового файла используй эти ID с минусом!")
