import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
import json, os, re

# --- Config laden oder erstellen ---
if not os.path.exists("config.json"):
    default_config = {
        "token": "YOUR_TOKEN_HERE",
        "guild_id": 0,
        "join_category_name": "🔊 Join to Create",
        "join_channel_name": "➕ Create",
        "control_text_channel": "voice-control",
        "count_channel": None,
        "count_state": {
            "current_number": 0,
            "last_user_id": None
        },
        "admin_only_count": False
    }
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4)

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

if "count_state" not in config:
    config["count_state"] = {"current_number": 0, "last_user_id": None}

TOKEN = config["token"]
GUILD_ID = config["guild_id"]
JOIN_CATEGORY_NAME = config["join_category_name"]
JOIN_CHANNEL_NAME = config["join_channel_name"]
CONTROL_TEXT_CHANNEL = config["control_text_channel"]
count_channel_id = config.get("count_channel", None)
admin_only_count = config.get("admin_only_count", False)

current_number = config["count_state"].get("current_number", 0)
last_user_id = config["count_state"].get("last_user_id", None)
created_channels = {}
voice_panel_created = set()  # Tracket Channels mit Panel

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def embed_response(title: str, description: str, color=discord.Color.blurple()):
    return discord.Embed(title=title, description=description, color=color)

def deleted_count_embed():
    return discord.Embed(
        title="🗑️ Nachricht gelöscht",
        description="Deine Nachricht wurde gelöscht, da im Count-Channel **nur Zahlen** erlaubt sind.",
        color=discord.Color.red()
    )

async def save_config():
    config["count_state"]["current_number"] = current_number
    config["count_state"]["last_user_id"] = last_user_id
    config["admin_only_count"] = admin_only_count
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

class ChannelControlView(View):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(timeout=None)
        self.channel = channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        perms = self.channel.permissions_for(interaction.user)
        if not (perms.connect and perms.manage_channels):
            await interaction.response.send_message(
                embed=embed_response(
                    "Fehler",
                    "❌ Du hast nicht die erforderlichen Rechte für diese Steuerung (Verbinden + Kanal verwalten).",
                    discord.Color.red()
                ),
                ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary)
    async def rename(self, interaction: discord.Interaction, button: Button):
        class RenameModal(Modal, title="Channel umbenennen"):
            new_name = TextInput(label="Neuer Name", style=discord.TextStyle.short)

            async def on_submit(self, modal_inter: discord.Interaction):
                await self.view.channel.edit(name=self.new_name.value)
                await modal_inter.response.send_message(
                    embed=embed_response(
                        "✅ Channel umbenannt",
                        f"Der Channel wurde zu **{self.new_name.value}** umbenannt.",
                        discord.Color.green()
                    ),
                    ephemeral=True
                )

            async def on_error(self, error: Exception, modal_inter: discord.Interaction):
                await modal_inter.response.send_message(
                    embed=embed_response(
                        "Fehler",
                        f"❌ Fehler beim Umbenennen: {error}",
                        discord.Color.red()
                    ), ephemeral=True)

        modal = RenameModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="➕ Limit", style=discord.ButtonStyle.secondary)
    async def increase_limit(self, interaction: discord.Interaction, button: Button):
        limit = self.channel.user_limit + 1 if self.channel.user_limit < 99 else 99
        await self.channel.edit(user_limit=limit)
        await interaction.response.send_message(
            embed=embed_response(
                "👥 User Limit erhöht",
                f"Das Nutzerlimit wurde auf **{limit}** gesetzt.",
                discord.Color.blue()
            ),
            ephemeral=True
        )

    @discord.ui.button(label="➖ Limit", style=discord.ButtonStyle.secondary)
    async def decrease_limit(self, interaction: discord.Interaction, button: Button):
        limit = self.channel.user_limit - 1 if self.channel.user_limit > 0 else 0
        await self.channel.edit(user_limit=limit)
        await interaction.response.send_message(
            embed=embed_response(
                "👥 User Limit verringert",
                f"Das Nutzerlimit wurde auf **{limit}** gesetzt.",
                discord.Color.blue()
            ),
            ephemeral=True
        )

    @discord.ui.button(label="🗑 Delete", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: Button):
        try:
            await self.channel.delete()
            await interaction.response.send_message(
                embed=embed_response(
                    "🗑 Channel gelöscht",
                    "Der Voice-Channel wurde gelöscht.",
                    discord.Color.red()
                ),
                ephemeral=True
            )
        except discord.NotFound:
            await interaction.response.send_message(
                embed=embed_response(
                    "Fehler",
                    "❌ Channel wurde bereits gelöscht oder existiert nicht mehr.",
                    discord.Color.red()
                ), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                embed=embed_response(
                    "Fehler",
                    f"❌ Fehler beim Löschen: {e}",
                    discord.Color.red()
                ), ephemeral=True)

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    category = discord.utils.get(guild.categories, name=JOIN_CATEGORY_NAME)

    if after.channel and after.channel.name == JOIN_CHANNEL_NAME:
        channel = await guild.create_voice_channel(
            name=f"{member.display_name}'s Channel",
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(connect=True),
                member: discord.PermissionOverwrite(manage_channels=True, connect=True, mute_members=True, move_members=True)
            }
        )
        await member.move_to(channel)
        created_channels[member.id] = channel.id

        control_channel = None
        if channel.category:
            for ch in channel.category.text_channels:
                if ch.name == CONTROL_TEXT_CHANNEL:
                    control_channel = ch
                    break
        if control_channel is None:
            control_channel = discord.utils.get(guild.text_channels, name=CONTROL_TEXT_CHANNEL)

        # Panel nur einmal pro Channel senden
        if control_channel and channel.id not in voice_panel_created:
            embed = embed_response(
                "🎛 Voice Control Panel",
                "Hier kannst du deinen Voice-Channel verwalten:\n"
                "• **Rename** – Ändere den Namen des Channels\n"
                "• **➕ Limit** – Nutzerlimit erhöhen\n"
                "• **➖ Limit** – Nutzerlimit verringern\n"
                "• **🗑 Delete** – Lösche den Channel\n\n"
                "*Nur Benutzer mit den Rechten Verbinden & Kanal verwalten können diese Steuerung verwenden.*",
                discord.Color.blurple()
            )
            view = ChannelControlView(channel)
            await control_channel.send(f"🔧 Steuerung für {member.mention}'s Channel:", embed=embed, view=view)
            voice_panel_created.add(channel.id)

    if before.channel and before.channel.id in created_channels.values():
        if len(before.channel.members) == 0:
            try:
                await before.channel.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Fehler beim Löschen des Channels: {e}")
            owner_id = None
            for k, v in created_channels.items():
                if v == before.channel.id:
                    owner_id = k
                    break
            if owner_id:
                del created_channels[owner_id]
            voice_panel_created.discard(before.channel.id)

@bot.event
async def on_message(message):
    global current_number, last_user_id, count_channel_id, admin_only_count

    if message.author.bot:
        return

    if count_channel_id and message.channel.id == count_channel_id:
        # Ignoriere Slash-Befehle im Count-Channel
        if message.content.strip().startswith('/'):
            return

        # Admin-only count check
        if admin_only_count:
            perms = message.author.guild_permissions
            if not perms.administrator:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                await message.channel.send(
                    embed=embed_response(
                        "Nicht erlaubt",
                        "❌ Nur Administratoren dürfen hier zählen.",
                        discord.Color.red()
                    ),
                    delete_after=7
                )
                return

        # Prüfe nur Zahlen mit regex
        if re.fullmatch(r"\d+", message.content.strip()):
            number = int(message.content.strip())

            if message.author.id == last_user_id:
                await message.add_reaction("❌")
                await message.channel.send(
                    embed=embed_response(
                        "Fehler",
                        "❌ Du darfst nicht zweimal hintereinander zählen!",
                        discord.Color.red()
                    ),
                    delete_after=7
                )
                current_number = 0
                last_user_id = None
                await save_config()
                return

            if number == current_number + 1:
                current_number += 1
                last_user_id = message.author.id
                await message.add_reaction("✅")
                await save_config()
            else:
                await message.add_reaction("❌")
                await message.channel.send(
                    embed=embed_response(
                        "Fehler",
                        "❌ Falsch gezählt! Wir starten wieder bei 1.",
                        discord.Color.red()
                    ),
                    delete_after=7
                )
                current_number = 0
                last_user_id = None
                await save_config()
        else:
            try:
                await message.delete()
            except discord.NotFound:
                pass
            await message.channel.send(
                embed=deleted_count_embed(),
                delete_after=7
            )
            return

    await bot.process_commands(message)

@bot.tree.command(name="setcount", description="Setzt den Channel für das Count-Spiel.")
@app_commands.checks.has_permissions(administrator=True)
async def setcount(interaction: discord.Interaction, channel: discord.TextChannel):
    global count_channel_id, current_number, last_user_id
    count_channel_id = channel.id
    config["count_channel"] = channel.id
    current_number = 0
    last_user_id = None
    await save_config()
    await interaction.response.send_message(
        embed=embed_response(
            "✅ Count Channel gesetzt",
            f"Der Count Channel wurde auf {channel.mention} gesetzt.",
            discord.Color.green()
        ), ephemeral=True)

@bot.tree.command(name="toggleadmincount", description="Schaltet das Zählen nur für Admins ein oder aus.")
@app_commands.checks.has_permissions(administrator=True)
async def toggleadmincount(interaction: discord.Interaction):
    global admin_only_count
    admin_only_count = not admin_only_count
    config["admin_only_count"] = admin_only_count
    await save_config()
    status_text = "aktiviert" if admin_only_count else "deaktiviert"
    await interaction.response.send_message(
        embed=embed_response(
            "✅ Admin-Only Count Status geändert",
            f"Das Zählen nur für Administratoren ist jetzt **{status_text}**.",
            discord.Color.green()
        ), ephemeral=True)

@bot.tree.command(name="lock", description="Sperrt einen Textkanal für normale User.")
@app_commands.checks.has_permissions(administrator=True)
async def lock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    embed = embed_response(
        "🔒 Channel gesperrt",
        "Du kannst hier momentan nicht schreiben.",
        discord.Color.red()
    )
    await channel.send(embed=embed)
    await interaction.response.send_message(
        embed=embed_response(
            "Erfolg",
            f"🔒 {channel.mention} wurde gesperrt.",
            discord.Color.green()
        ), ephemeral=True)

@bot.tree.command(name="unlock", description="Entsperrt einen Textkanal für normale User.")
@app_commands.checks.has_permissions(administrator=True)
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = True
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    embed = embed_response(
        "🔓 Channel entsperrt",
        "Du kannst hier wieder schreiben.",
        discord.Color.green()
    )
    await channel.send(embed=embed)
    await interaction.response.send_message(
        embed=embed_response(
            "Erfolg",
            f"🔓 {channel.mention} wurde entsperrt.",
            discord.Color.green()
        ), ephemeral=True)

@bot.tree.command(name="purge", description="Löscht die letzten X Nachrichten.")
@app_commands.checks.has_permissions(administrator=True)
async def purge(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(
        embed=embed_response(
            "🧹 Nachrichten gelöscht",
            f"{len(deleted)} Nachrichten wurden entfernt.",
            discord.Color.green()
        ), ephemeral=True)

@bot.tree.command(name="setup", description="Erstellt automatisch Kategorie, Voice & Control-Channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=JOIN_CATEGORY_NAME)
    if not category:
        category = await guild.create_category(JOIN_CATEGORY_NAME)

    join_channel = discord.utils.get(category.voice_channels, name=JOIN_CHANNEL_NAME)
    if not join_channel:
        join_channel = await guild.create_voice_channel(JOIN_CHANNEL_NAME, category=category)

    control_channel = discord.utils.get(guild.text_channels, name=CONTROL_TEXT_CHANNEL)
    if not control_channel:
        control_channel = await guild.create_text_channel(CONTROL_TEXT_CHANNEL, category=category)

    config["guild_id"] = guild.id
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    await interaction.response.send_message(
        embed=embed_response(
            "✅ Setup abgeschlossen",
            "Kategorie, Create-Voice-Channel & Control-Channel wurden erstellt.",
            discord.Color.green()
        ), ephemeral=True)

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID) if GUILD_ID != 0 else None
    if guild:
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    print(f"✅ Bot gestartet als {bot.user}")

bot.run(TOKEN)
