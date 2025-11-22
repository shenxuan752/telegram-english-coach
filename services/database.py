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
