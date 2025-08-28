import discord
from discord.ext import commands
import speech_recognition as sr
import asyncio # Required for delays
import os # Added for environment variables

# --- Bot Configuration ---
# The bot token is now loaded from an environment variable for security.
# You will need to set this in your hosting service's dashboard (e.g., Railway).
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
WAKE_WORD = "hey bot"  # Example wake word
COMMAND_PREFIX = "!"  # Traditional text command prefix

intents = discord.Intents.default()
intents.members = True  # Required for member information
intents.voice_states = True  # To know who is in voice channels
intents.message_content = True # To read text commands and for message content in general

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
recognizer = sr.Recognizer()

# --- Bot Events ---
@bot.event
async def on_ready():
    """
    Called when the bot is done preparing the data received from Discord.
    Usually after login successfully.
    """
    print(f'{bot.user.name} has connected to Discord!')
    print(f"Listening for wake word (conceptually): '{WAKE_WORD}'")
    print(f"Text command prefix: '{COMMAND_PREFIX}'")

# --- Voice Channel Connection ---
@bot.command(name='join')
async def join_voice(ctx):
    """Allows the bot to join the voice channel of the command issuer."""
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        try:
            if ctx.voice_client is not None:
                # If already in a voice channel, move to the new one
                return await ctx.voice_client.move_to(channel)
            # Connect to the voice channel
            vc = await channel.connect()
            await ctx.send(f"Joined {channel.name}. Ready for voice commands (use `{COMMAND_PREFIX}listen_once` for demo).")
        except discord.ClientException as e:
            await ctx.send(f"Error connecting to voice channel: {e}")
        except Exception as e:
            await ctx.send(f"An unexpected error occurred while joining: {e}")
    else:
        await ctx.send("You are not connected to a voice channel.")

@bot.command(name='leave')
async def leave_voice(ctx):
    """Allows the bot to leave its current voice channel."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.")
    else:
        await ctx.send("I am not connected to a voice channel.")

# --- Voice Command Processing (Core Logic) ---
async def process_voice_command_logic(audio_data, ctx, listening_message):
    """
    Processes the recorded audio data to text and then to a command.
    """
    try:
        # Using Google Web Speech API for recognition
        text = recognizer.recognize_google(audio_data).lower()
        await listening_message.edit(content=f"Recognized: \"{text}\"")
        print(f"User {ctx.author.display_name} said: {text}")

        command_text = text
        if not command_text: # Should be caught by sr.UnknownValueError if no speech
            await ctx.send("No command recognized from the audio.", delete_after=10)
            return

        await parse_and_execute_moderation(command_text, ctx)

    except sr.UnknownValueError:
        await listening_message.edit(content="Sorry, I did not understand the audio.", delete_after=10)
        print("Speech Recognition: Could not understand audio")
    except sr.RequestError as e:
        await listening_message.edit(content=f"Speech recognition service error; {e}", delete_after=10)
        print(f"Speech Recognition: Could not request results; {e}")
    except Exception as e:
        await listening_message.edit(content=f"Error processing voice command: {e}", delete_after=10)
        print(f"Error processing voice command: {e}")


# --- Simplified Listening Command for Demonstration ---
@bot.command(name='listen_once')
async def listen_once(ctx):
    """
    Listens for a single voice command using the host's microphone.
    For production, Discord audio sinks are needed.
    """
    if not ctx.voice_client:
        await ctx.send(f"I'm not in a voice channel. Use `{COMMAND_PREFIX}join` first.")
        return

    listening_message = await ctx.send("Listening for a command (5 seconds)...")

    # This uses the host's microphone. For actual Discord audio, use Sinks.
    # Note: This part will not work on a typical hosting service like Railway
    # because they don't have a microphone. This command is for local testing only.
    try:
        with sr.Microphone() as source:
            # Adjust for ambient noise dynamically
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            await listening_message.edit(content="Listening via host microphone...")
            print("Listening via host microphone...")
            # Listen for a phrase. Timeout if no speech starts after 5s.
            # phrase_time_limit stops recording after 5s of speech.
            audio_data = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            print("Finished listening via host microphone.")
            await process_voice_command_logic(audio_data, ctx, listening_message)
    except OSError:
        await listening_message.edit(content="No microphone found. This command only works on a local machine with a microphone.", delete_after=15)
        print("OSError: No microphone found. Cannot use listen_once command on this host.")
    except sr.WaitTimeoutError:
        await listening_message.edit(content="No speech detected within the time limit.", delete_after=10)
        print("No speech detected via host microphone.")
    except Exception as e:
        await listening_message.edit(content=f"An error occurred with the microphone: {e}", delete_after=10)
        print(f"Error with host microphone: {e}")


# --- Command Parsing and Execution ---
async def parse_and_execute_moderation(command_text, ctx):
    """
    Parses the recognized text and executes the corresponding moderation action.
    """
    normalized_command_text = command_text.lower().strip()
    guild = ctx.guild
    bot_member = guild.me # The bot itself as a Member object
    reason_text = f"Voice command from {ctx.author.display_name}"

    # --- Helper function for mass operations ---
    async def perform_mass_action(action_type, target_channel_for_move=None):
        helper_action_message = None # Message to be sent/edited by this helper

        if not ctx.voice_client or not ctx.voice_client.channel:
            await ctx.send("I'm not in a voice channel to perform this action.", delete_after=10)
            return

        current_vc = ctx.voice_client.channel
        required_permission_name = None
        action_verb_present = "" # e.g., "muting"
        action_verb_past = ""    # e.g., "muted"

        if action_type == "mute":
            required_permission_name = "mute_members"
            action_verb_present = "muting"
            action_verb_past = "muted"
        elif action_type == "unmute":
            required_permission_name = "mute_members"
            action_verb_present = "unmuting"
            action_verb_past = "unmuted"
        elif action_type == "move":
            required_permission_name = "move_members"
            action_verb_present = "moving"
            action_verb_past = "moved"
            if not target_channel_for_move:
                await ctx.send("Target channel not specified for mass move.", delete_after=10)
                return
            if target_channel_for_move == current_vc:
                await ctx.send(f"Everyone is already in {target_channel_for_move.name}.", delete_after=10)
                return
        elif action_type == "disconnect":
            required_permission_name = "move_members" # Disconnecting uses move_members permission
            action_verb_present = "disconnecting"
            action_verb_past = "disconnected"

        # Check bot's permissions
        if required_permission_name and not getattr(bot_member.guild_permissions, required_permission_name, False):
            await ctx.send(f"I don't have permission to {action_verb_present.replace('ing', '')} members.", delete_after=10)
            return

        # Get members to affect (exclude bot and the command issuer)
        members_to_affect = [
            member for member in current_vc.members if member != bot_member and member != ctx.author
        ]

        if not members_to_affect:
            await ctx.send(f"No one else to {action_verb_present.replace('ing', '')} in {current_vc.name} (besides you and me).", delete_after=10)
            return
        
        helper_action_message = await ctx.send(f"Attempting to {action_verb_present} everyone in {current_vc.name}...", delete_after=25)
        processed_count = 0
        failed_to_process_names = []

        for member_to_act_on in members_to_affect:
            # Role hierarchy check: Bot cannot moderate someone with equal/higher top role unless bot is owner
            if bot_member.top_role <= member_to_act_on.top_role and guild.owner != bot_member:
                print(f"Cannot {action_verb_present.replace('ing', '')} {member_to_act_on.display_name} due to role hierarchy.")
                failed_to_process_names.append(member_to_act_on.display_name + " (role)")
                continue
            try:
                if action_type == "mute":
                    if not member_to_act_on.voice.mute: # Only mute if not already muted
                        await member_to_act_on.edit(mute=True, reason=f"{reason_text} (mass mute)")
                        processed_count += 1
                elif action_type == "unmute":
                    if member_to_act_on.voice.mute: # Only unmute if currently muted
                        await member_to_act_on.edit(mute=False, reason=f"{reason_text} (mass unmute)")
                        processed_count += 1
                elif action_type == "move":
                    await member_to_act_on.move_to(target_channel_for_move, reason=f"{reason_text} (mass move)")
                    processed_count += 1
                elif action_type == "disconnect":
                     await member_to_act_on.edit(voice_channel=None, reason=f"{reason_text} (mass disconnect)")
                     processed_count +=1

                print(f"{action_verb_past.capitalize()} {member_to_act_on.display_name}.")
                await asyncio.sleep(0.2) # Be kind to the API
            except discord.Forbidden:
                print(f"Permission denied to {action_verb_present.replace('ing','')} {member_to_act_on.display_name}")
                failed_to_process_names.append(member_to_act_on.display_name + " (perm)")
            except discord.HTTPException as e:
                print(f"HTTP error {action_verb_present.replace('ing','')} {member_to_act_on.display_name}: {e.status}")
                failed_to_process_names.append(member_to_act_on.display_name + f" (http: {e.status})")
            except Exception as e:
                print(f"Unexpected error {action_verb_present.replace('ing','')} {member_to_act_on.display_name}: {e}")
                failed_to_process_names.append(member_to_act_on.display_name + " (err)")

        feedback = f"{action_verb_past.capitalize()} {processed_count} member(s)."
        if action_type == "move":
            feedback += f" to {target_channel_for_move.name}."
        elif action_type not in ["disconnect"]: # Mute/Unmute happen "in channel"
             feedback += f" in {current_vc.name}."
        # For disconnect, "Disconnected X members." is fine.

        if failed_to_process_names:
            feedback += f" Failed for: {', '.join(failed_to_process_names)}."
        
        if helper_action_message: # Should always be true if members_to_affect was not empty
            await helper_action_message.edit(content=feedback, delete_after=20)
        else: # Fallback, though unlikely to be reached if logic is correct
            await ctx.send(feedback, delete_after=20)
    # --- End of Helper function ---

    # --- Mass Action Command Handling ---
    if normalized_command_text in ["kick them", "disconnect everyone"]:
        await perform_mass_action("disconnect")
        return
    elif normalized_command_text == "mute them":
        await perform_mass_action("mute")
        return
    elif normalized_command_text == "unmute them":
        await perform_mass_action("unmute")
        return
    elif normalized_command_text.startswith("move them to "):
        target_channel_name_str = normalized_command_text.replace("move them to ", "").strip()
        if not target_channel_name_str:
            await ctx.send("Please specify a target channel name for 'move them to ...'.", delete_after=10)
            return

        # Resolve target voice channel
        target_vc_obj_for_mass_move = discord.utils.get(guild.voice_channels, name=target_channel_name_str)
        if not target_vc_obj_for_mass_move:
            found_channels = [
                vc for vc in guild.voice_channels if target_channel_name_str.lower() in vc.name.lower()
            ]
            if len(found_channels) == 1:
                target_vc_obj_for_mass_move = found_channels[0]
            elif len(found_channels) > 1:
                await ctx.send(f"Found multiple voice channels for '{target_channel_name_str}'. Be more specific.", delete_after=10)
                return
            else:
                await ctx.send(f"Could not find voice channel '{target_channel_name_str}'.", delete_after=10)
                return
        await perform_mass_action("move", target_channel_for_move=target_vc_obj_for_mass_move)
        return
    # --- End Mass Action Command Handling ---

    # --- Individual Action Command Parsing (if not a mass action) ---
    words = normalized_command_text.split()
    if not words:
        await ctx.send("No command detected in voice input.", delete_after=10)
        return

    action_word = words[0]
    member_name_parts = words[1:]

    possible_actions_map = {
        "mute": "mute", "unmute": "unmute",
        "move": "move",
        "disconnect": "disconnect", "kick": "disconnect", "remove": "disconnect",
        "ban": "ban"
    }

    current_action = possible_actions_map.get(action_word)

    if not current_action:
        await ctx.send(f"Unrecognized action: '{action_word}'. Please say 'action member_name'.", delete_after=10)
        return

    if not member_name_parts:
        await ctx.send(f"Please specify a member name after the action '{current_action}'.", delete_after=10)
        return

    target_member_obj = None
    target_voice_channel_for_individual_move = None

    if current_action == "move":
        if "to" not in member_name_parts:
            await ctx.send("For 'move', please say 'move member_name to target_channel_name'.", delete_after=10)
            return
        try:
            to_keyword_index = member_name_parts.index("to")
        except ValueError:
            await ctx.send("Malformed 'move' command. Use: 'move member_name to target_channel_name'.", delete_after=10); return
        
        actual_member_name_str = " ".join(member_name_parts[:to_keyword_index])
        target_channel_name_for_move_str = " ".join(member_name_parts[to_keyword_index+1:])

        if not actual_member_name_str or not target_channel_name_for_move_str:
            await ctx.send("Missing member name or target channel name for 'move'.", delete_after=10); return
        
        member_name_to_find = actual_member_name_str
        target_member_obj = discord.utils.get(guild.members, display_name=member_name_to_find) or \
                            discord.utils.get(guild.members, name=member_name_to_find)
        if not target_member_obj:
            found_members_list = [m for m in guild.members if member_name_to_find.lower() in m.display_name.lower() or member_name_to_find.lower() in m.name.lower()]
            if len(found_members_list) == 1: target_member_obj = found_members_list[0]
            elif len(found_members_list) > 1: await ctx.send(f"Multiple members found for '{member_name_to_find}'. Be more specific.", delete_after=10); return
            else: await ctx.send(f"Could not find member '{member_name_to_find}'.", delete_after=10); return
        
        target_voice_channel_for_individual_move = discord.utils.get(guild.voice_channels, name=target_channel_name_for_move_str)
        if not target_voice_channel_for_individual_move:
            found_channels_list = [vc for vc in guild.voice_channels if target_channel_name_for_move_str.lower() in vc.name.lower()]
            if len(found_channels_list) == 1: target_voice_channel_for_individual_move = found_channels_list[0]
            elif len(found_channels_list) > 1: await ctx.send(f"Multiple voice channels found for '{target_channel_name_for_move_str}'. Be more specific.", delete_after=10); return
            else: await ctx.send(f"Could not find voice channel '{target_channel_name_for_move_str}'.", delete_after=10); return
    else:
        member_name_to_find = " ".join(member_name_parts)
        target_member_obj = discord.utils.get(guild.members, display_name=member_name_to_find) or \
                            discord.utils.get(guild.members, name=member_name_to_find)
        if not target_member_obj:
            found_members_list = [
                m for m in guild.members if member_name_to_find.lower() in m.display_name.lower() or member_name_to_find.lower() in m.name.lower()
            ]
            if len(found_members_list) == 1:
                target_member_obj = found_members_list[0]
            elif len(found_members_list) > 1:
                names_found = ", ".join([m.display_name for m in found_members_list[:3]])
                await ctx.send(f"Multiple members match '{member_name_to_find}': {names_found}. Please be more specific.", delete_after=10); return
            else:
                await ctx.send(f"Could not find member '{member_name_to_find}'.", delete_after=10); return

    if not target_member_obj:
        await ctx.send("Failed to identify the target member after checks.", delete_after=10)
        return

    # --- Execute Individual Actions ---
    try:
        if current_action == "mute":
            if not bot_member.guild_permissions.mute_members: await ctx.send("I don't have permission to mute members.", delete_after=10); return
            if target_member_obj.voice and target_member_obj.voice.channel:
                if not target_member_obj.voice.mute:
                    await target_member_obj.edit(mute=True, reason=reason_text)
                    await ctx.send(f"Voice muted {target_member_obj.display_name}.", delete_after=10)
                else:
                    await ctx.send(f"{target_member_obj.display_name} is already voice muted.", delete_after=10)
            else:
                await ctx.send(f"{target_member_obj.display_name} is not in a voice channel.", delete_after=10)

        elif current_action == "unmute":
            if not bot_member.guild_permissions.mute_members: await ctx.send("I don't have permission to unmute members.", delete_after=10); return
            if target_member_obj.voice and target_member_obj.voice.channel:
                if target_member_obj.voice.mute:
                    await target_member_obj.edit(mute=False, reason=reason_text)
                    await ctx.send(f"Voice unmuted {target_member_obj.display_name}.", delete_after=10)
                else:
                    await ctx.send(f"{target_member_obj.display_name} is not currently voice muted.", delete_after=10)
            else:
                await ctx.send(f"{target_member_obj.display_name} is not in a voice channel.", delete_after=10)

        elif current_action == "move":
            if not bot_member.guild_permissions.move_members: await ctx.send("I don't have permission to move members.", delete_after=10); return
            if not target_member_obj.voice or not target_member_obj.voice.channel: await ctx.send(f"{target_member_obj.display_name} is not in a voice channel to be moved.", delete_after=10); return
            if not target_voice_channel_for_individual_move: await ctx.send(f"Target channel for move not resolved correctly.", delete_after=10); return
            if target_member_obj.voice.channel == target_voice_channel_for_individual_move: await ctx.send(f"{target_member_obj.display_name} is already in {target_voice_channel_for_individual_move.name}.", delete_after=10); return
            
            await target_member_obj.move_to(target_voice_channel_for_individual_move, reason=reason_text)
            await ctx.send(f"Moved {target_member_obj.display_name} to {target_voice_channel_for_individual_move.name}.", delete_after=10)

        elif current_action == "disconnect":
            if not bot_member.guild_permissions.move_members: await ctx.send("I don't have permission to disconnect members.", delete_after=10); return
            if target_member_obj.voice and target_member_obj.voice.channel:
                await target_member_obj.edit(voice_channel=None, reason=reason_text)
                await ctx.send(f"Disconnected {target_member_obj.display_name} from voice.", delete_after=10)
            else:
                await ctx.send(f"{target_member_obj.display_name} is not in a voice channel.", delete_after=10)

        elif current_action == "ban":
            if not bot_member.guild_permissions.ban_members: await ctx.send("I don't have permission to ban members.", delete_after=10); return
            if bot_member.top_role <= target_member_obj.top_role and guild.owner != bot_member:
                 await ctx.send(f"I cannot ban {target_member_obj.display_name} due to role hierarchy.", delete_after=10); return
            
            await target_member_obj.ban(reason=reason_text, delete_message_days=0)
            await ctx.send(f"Banned {target_member_obj.display_name}.", delete_after=10)

    except discord.Forbidden:
        await ctx.send(f"I lack permissions to perform '{current_action}' on {target_member_obj.display_name}. This could be due to my role being too low, or missing a specific permission.", delete_after=10)
    except discord.HTTPException as e:
        await ctx.send(f"A Discord API error occurred: {e.status} - {e.text}", delete_after=10)
    except Exception as e:
        print(f"Error during moderation action {current_action} on {target_member_obj.display_name if target_member_obj else 'N/A'}: {e}")
        await ctx.send(f"An unexpected error occurred trying to {current_action} {target_member_obj.display_name if target_member_obj else 'them'}: {e}", delete_after=10)


# --- Running the Bot ---
if __name__ == "__main__":
    # The bot token is now fetched from an environment variable.
    # This check ensures the bot doesn't try to run without a token.
    if BOT_TOKEN:
        try:
            bot.run(BOT_TOKEN)
        except discord.LoginFailure:
            print("ERROR: Login failed. Make sure your DISCORD_TOKEN is correct and valid.")
        except TypeError as e:
            print(f"ERROR: TypeError encountered: {e}. Check your intents or event setup.")
        except Exception as e:
            print(f"ERROR: An error occurred while trying to run the bot: {e}")
    else:
        print("ERROR: DISCORD_TOKEN environment variable not found.")
        print("Please set the DISCORD_TOKEN in your hosting service's configuration (e.g., Railway variables).")

