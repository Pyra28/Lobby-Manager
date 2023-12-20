import requests
import discord
from discord.ext import tasks, commands
import logging
import datetime

# Global variables
match_keywords = ['keyword1', 'keyword2', 'keyword3', 'keyword4', 'keyword5']
omit_keywords = ['keyword1', 'keyword2', 'keyword3', 'keyword4', 'keyword5']

master_match_data = {}
match_id_row_mapping = {}
creation_times = {}

DISCORD_TOKEN = 'DISCORD_BOT_TOKEN'
CHANNEL_ID = copy_channel_id_here

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Configure logging to write messages to a file
logging.basicConfig(filename='ConsoleLogger.txt', level=logging.INFO)


def make_api_request(api_url):
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        return response.json().get('matches', [])
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return []


def create_lobby_link(match_id):
    return f"https://aoe2lobby.com/j/{match_id}"


class MyView(discord.ui.View):
    def __init__(self, description, host_id, match_id):
        super().__init__(timeout=None)  # No timeout

        lobby_link = create_lobby_link(match_id)

        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="Join Lobby",
            url=lobby_link
        ))

        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.blurple,
            label="Host's Profile",
            url=f"https://www.aoe2insights.com/user/{host_id}/"
        ))

        self.description = f">>> **__Lobby: {description}"
        self.host_id = host_id
        self.match_id = match_id
        self.message = None  # Initialize message attribute

        # Set creation time for this instance
        creation_times[match_id] = datetime.datetime.utcnow()

    async def on_timeout(self):
        # No timeout behavior, or you can define custom behavior
        pass


@bot.event
async def on_ready():
    logging.info(f'{bot.user} Has Successfully Logged In.')
    background_task.start()


async def update_message(api_data, channel, match_id, match_description, host_id):
    if match_id in match_id_row_mapping:
        message_id = match_id_row_mapping[match_id]

        try:
            target_message = await channel.fetch_message(message_id)
        except discord.errors.NotFound:
            return

        if target_message:
            match_data = next((match for match in api_data if match.get('id') == match_id), None)
            description = f">>> **__Lobby: {match_description}__**\n*   *Players: ({len(match_data.get('matchmembers'))}/8)*" if match_data else "**No Longer Available**"

            # Fetch player aliases using the profile IDs in the lobby
            player_aliases = await get_alias_for_profile_ids(match_data.get('matchmembers')) if match_data else []

            # Replace empty spots with "Open"
            player_aliases = [alias if alias else "Open" for alias in player_aliases]

            if player_aliases:
                # Ensure we have at least 8 elements in the list
                player_aliases += ["Open"] * (8 - len(player_aliases))

                players_text = f"```\n{', '.join(player_aliases[:4])},\n{', '.join(player_aliases[4:])}.\n```"
                description += f"\n{players_text}"

            # Get the creation time from the dictionary
            creation_time = creation_times.get(match_id)

            if creation_time:
                time_difference = datetime.datetime.utcnow() - creation_time

                if time_difference.total_seconds() > 895:
                    try:
                        await target_message.delete()
                    except Exception as e:
                        print(f"Error deleting message: {e}")

                    # Send a new message with updated information
                    try:
                        new_view = MyView(description, host_id, match_id)
                        new_message = await channel.send(new_view.description, view=new_view)
                        # Update the mapping with the new message ID
                        match_id_row_mapping[match_id] = new_message.id
                        # Update the creation time in the dictionary
                        creation_times[match_id] = datetime.datetime.utcnow()
                    except Exception as e:
                        print(f"Error sending new message: {e}")

                else:
                    # If within 15 minutes, edit the existing message
                    try:
                        await target_message.edit(content=description)
                    except Exception as e:
                        print(f"Error editing message: {e}")


async def get_alias_for_profile_ids(matchmembers):
    # Fetch player aliases using the profile IDs in matchmembers
    aliases = []

    for member in matchmembers:
        profile_id = member.get('profile_id')
        alias = await get_alias_for_profile_id(profile_id)
        aliases.append(alias)

    return aliases


async def get_alias_for_profile_id(profile_id):
    # Make a request to get the avatars data
    response = requests.get("https://aoe-api.worldsedgelink.com/community/advertisement/findAdvertisements?title=age2&count=100&start=0")

    if response.status_code == 200:
        # Parse the response JSON
        avatars_data = response.json().get("avatars", [])

        # Create a dictionary to map profile IDs to aliases
        profile_id_to_alias = {player["profile_id"]: player["alias"] for player in avatars_data}

        # Get the alias for the provided profile ID
        alias = profile_id_to_alias.get(profile_id, "Unknown")
        return alias
    else:
        print(f"Error retrieving avatars data. Status code: {response.status_code}")
        return None


async def check_closed_matches(api_data):
    global master_match_data

    # Get the match IDs from the raw API data
    api_match_ids = {match['id'] for match in api_data}

    # Find closed matches
    closed_matches = set(master_match_data.keys()) - api_match_ids

    logging.info("Closed matches: {}".format(closed_matches))  # Add this line

    for closed_match_id in closed_matches:
        logging.info(f"Processing closed match ID: {closed_match_id}")  # Add this line

        # Get the corresponding match data, message ID, and description
        match_data_entry = master_match_data[closed_match_id]
        match_data = match_data_entry.get('match_data')
        message_id = match_data_entry['message_id']

        # Check if the closed match is still present in the updated API data
        if match_data and match_data['id'] in api_match_ids:
            logging.info(f"Closed match ID {closed_match_id} is still open.")
            continue  # Skip if the match is still open

        logging.info(f"Updating closed match ID: {closed_match_id}")

        description = f"**[No Longer Available: {match_data.get('description')}]**"

        channel_id = CHANNEL_ID
        channel = bot.get_channel(channel_id)

        if channel:
            try:
                # Fetch the message and update it
                target_message = await channel.fetch_message(message_id)
                await target_message.edit(content=description, view=None)  # Remove buttons
                logging.info(f"Closed match ID {closed_match_id} updated successfully.")  # Add this line
            except discord.errors.NotFound:
                logging.error(f"Message with ID {message_id} not found.")
                continue

            # Remove the closed match from the mapping
            del master_match_data[closed_match_id]
            logging.info(f"Closed match ID {closed_match_id} removed from master_match_data.")


@tasks.loop(seconds=5)
async def background_task():
    global master_match_data

    update_api_url = "https://aoe-api.worldsedgelink.com/community/advertisement/findAdvertisements?title=age2&count=100&start=0"
    api_data = make_api_request(update_api_url)

    # Create a list to store match IDs that need to be removed from the mapping
    matches_to_remove = []

    for match_id, message_id in match_id_row_mapping.items():
        match_data = next((match for match in api_data if match.get('id') == match_id), None)

        logging.info(f"Processing match ID: {match_id}, Match Data: {match_data}")

        # If the lobby is not found in the updated API data, mark it for removal
        if match_data is None:
            matches_to_remove.append(match_id)
            logging.warning(f"Match ID {match_id} not found in updated API data. Marking for removal.")
        else:
            # Update or add the match ID to the master list
            master_match_data[match_id] = {'match_data': match_data, 'message_id': message_id}

    logging.info("Matches to remove: {}".format(matches_to_remove))

    # Remove entries from the mapping
    for match_id in matches_to_remove:
        del match_id_row_mapping[match_id]
        logging.info(f"Removed match ID {match_id} from mapping.")

    for match in api_data:
        match_id = match.get('id')
        description_lower = match.get('description').lower()

        if any(keyword.lower() in description_lower for keyword in match_keywords) and \
                not any(omit_keyword.lower() in description_lower for omit_keyword in omit_keywords):

            channel_id = CHANNEL_ID
            channel = bot.get_channel(channel_id)

            if match_id not in match_id_row_mapping and channel:
                description = "{}__**\n*    *Players: ({}/8)*".format(match.get('description'), len(match.get('matchmembers')))
                host_id = str(match.get('host_profile_id'))

                # Fetch player aliases using the profile IDs in the lobby
                player_aliases = await get_alias_for_profile_ids(match.get('matchmembers')) if match else []

                # Replace empty spots with "Open"
                player_aliases = [alias if alias else "Open" for alias in player_aliases]

                # Ensure we have at least 8 elements in the list
                player_aliases += ["Open"] * (8 - len(player_aliases))

                players_text = f"```\n{', '.join(player_aliases[:4])},\n{', '.join(player_aliases[4:]).rstrip(',')}.```"
                description += f"\n{players_text}"

                view = MyView(description, host_id, match_id)
                message = await channel.send(view.description, view=view)
                match_id_row_mapping[match_id] = message.id
            elif match_id in match_id_row_mapping and channel:
                host_id = str(match.get('host_profile_id'))

                await update_message(api_data, channel, match_id, match.get('description'), host_id)

    # Check for closed matches and update messages
    await check_closed_matches(api_data)

    # Update the master list with the latest match data and message IDs
    master_match_data = {
        match_id: {'match_data': match_data_entry['match_data'], 'message_id': match_data_entry['message_id']}
        for match_id, match_data_entry in master_match_data.items() if
        match_data_entry.get('match_data') and match_id in match_id_row_mapping
    }


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
