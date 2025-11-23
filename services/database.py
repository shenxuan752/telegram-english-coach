from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

async def save_flashcard(word_data: dict, user_id: int):
    """Save flashcard to Supabase, avoiding duplicates."""
    # Check if word already exists for this user
    existing = supabase.table('flashcards').select('id').eq('user_id', str(user_id)).eq('word', word_data['word']).execute()
    
    if existing.data:
        return {'status': 'skipped', 'message': 'Word already exists'}
    
    data = {
        **word_data,
        'user_id': str(user_id)
    }
    result = supabase.table('flashcards').insert(data).execute()
    return result.data

async def get_flashcards(user_id: int, limit: int = 20):
    """Get user's flashcards."""
    result = supabase.table('flashcards').select('*').eq('user_id', str(user_id)).order('created_at', desc=True).limit(limit).execute()
    return result.data

async def save_journal(entry_data: dict, user_id: int):
    """Save journal entry."""
    data = {
        **entry_data,
        'user_id': str(user_id)
    }
    result = supabase.table('journal_entries').insert(data).execute()
    return result.data


async def get_random_journal(user_id: int):
    """Get a random journal entry for the user."""
    result = supabase.table('journal_entries').select('*').eq('user_id', str(user_id)).execute()
    if result.data and len(result.data) > 0:
        import random
        return random.choice(result.data)
    return None

async def save_mission_completion(mission_data: dict, user_id: int):
    """Save completed mission."""
    data = {
        **mission_data,
        'user_id': str(user_id)
    }
    result = supabase.table('missions').insert(data).execute()
    return result.data

async def save_user(user_id: int):
    """Save user to track active users for schedule restoration."""
    try:
        # Check if user exists
        existing = supabase.table('english_coach_users').select('user_id').eq('user_id', str(user_id)).execute()
        if not existing.data:
            data = {'user_id': str(user_id)}
            supabase.table('english_coach_users').insert(data).execute()
            print(f"✅ Saved new user: {user_id}")
            return True
    except Exception as e:
        print(f"⚠️ Error saving user (table may not exist): {e}")
    return False

async def get_all_users():
    """Get all active users to restore schedules."""
    try:
        result = supabase.table('english_coach_users').select('user_id').execute()
        return [int(user['user_id']) for user in result.data] if result.data else []
    except Exception as e:
        print(f"⚠️ Error getting users (table may not exist): {e}")
        # Return empty list if table doesn't exist - bot will still work for new users
        return []
