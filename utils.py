import random
from math import floor
from datetime import datetime

AFRICAN_COUNTRIES = [
    'Algeria','Angola','Benin','Botswana','Burkina Faso','Burundi','Cabo Verde','Cameroon','Central African Republic',
    'Chad','Comoros','Congo','DR Congo','Cote d\'Ivoire','Djibouti','Egypt','Equatorial Guinea','Eritrea','Eswatini',
    'Ethiopia','Gabon','Gambia','Ghana','Guinea','Guinea-Bissau','Kenya','Lesotho','Liberia','Libya','Madagascar',
    'Malawi','Mali','Mauritania','Mauritius','Morocco','Mozambique','Namibia','Niger','Nigeria','Rwanda','Sao Tome and Principe',
    'Senegal','Seychelles','Sierra Leone','Somalia','South Africa','South Sudan','Sudan','Tanzania','Togo','Tunisia','Uganda','Zambia','Zimbabwe'
]

FIRST_NAMES = ['John','Ali','Mohamed','David','Samuel','Joseph','Michael','Pierre','Kwame','Carlos','Ahmed','Youssef','Kofi','Suleiman','Ibrahim']
LAST_NAMES = ['Mensah','Kone','Diallo','Okoye','Moyo','Kamau','Ndlovu','Nguyen','Osei','Smith','Johnson','Brown','Doe']
POSITIONS = ['GK','DF','MD','AT']

# Local hosted assets (place files in flask_app/static/assets/)
ASSETS = {
    'goal_sfx': '/static/assets/goal.ogg',
    'crowd_cheer': '/static/assets/crowd.ogg',
    # prefer small animated webp files
    'key_moment_gifs': [
        '/static/assets/gif1.webp',
        '/static/assets/gif2.webp',
        '/static/assets/gif3.webp'
    ],
}

# Fallback external GIFs in case local webp not available
FALLBACK_GIFS = [
    'https://media.giphy.com/media/3o6ZtaO9BZHcOjmErm/giphy.gif',
    'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif',
    'https://media.giphy.com/media/26FPJWvYk8Z1nNvNK/giphy.gif'
]

import os

def get_gif_url(local_path):
    """Return local URL if file exists, otherwise a fallback external GIF URL."""
    # local_path is like '/static/assets/gif1.webp'
    project_root = os.path.dirname(__file__)
    # compute filesystem path to static asset
    fs_path = os.path.join(project_root, local_path.lstrip('/'))
    if os.path.exists(fs_path):
        return local_path
    # choose fallback
    return random.choice(FALLBACK_GIFS)


def rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def generate_player(i=0):
    name = rand_name()
    natural = random.choices(POSITIONS, weights=[0.05,0.4,0.35,0.2])[0]
    return {'name': name, 'natural': natural}

def build_player(name, natural):
    # create ratings based on natural position
    ratings = {}
    for pos in POSITIONS:
        if pos == natural:
            ratings[pos] = random.randint(50,100)
        else:
            ratings[pos] = random.randint(0,50)
    return {'name': name, 'natural': natural, 'ratings': ratings}

def team_rating(players):
    totals = 0
    for p in players:
        nat = p.get('natural')
        if nat:
            totals += p['ratings'][nat]
        else:
            totals += max(p['ratings'].values())
    return round(totals / max(1, len(players)), 2)

# Bracket creation: create quarterfinal matches
def make_bracket(teams):
    teams_copy = teams[:]
    random.shuffle(teams_copy)
    matches = []
    stage = 'Quarterfinal'
    for i in range(0,8,2):
        t1 = teams_copy[i]
        t2 = teams_copy[i+1]
        m = {
            'team1': t1['_id'],
            'team2': t2['_id'],
            'team1_country': t1['country'],
            'team2_country': t2['country'],
            'stage': stage,
            'score1': None,
            'score2': None,
            'scorers': [],
            'played': False,
            'created_at': datetime.utcnow()
        }
        matches.append(m)
    return matches

# Simulate match with simple probability based on team rating
import random

def simulate_match(team1, team2, use_commentary=False, openai_client=None):
    r1 = team1.get('rating', 50)
    r2 = team2.get('rating', 50)
    mean1 = max(0.2, (r1 / (r1 + r2)) * 3)
    mean2 = max(0.2, (r2 / (r1 + r2)) * 3)
    score1 = poisson_random(mean1)
    score2 = poisson_random(mean2)
    scorers = []
    for _ in range(score1):
        player = choose_scorer(team1['players'])
        minute = random_minute()
        gif_local = random.choice(ASSETS['key_moment_gifs'])
        gif_url = get_gif_url(gif_local)
        scorers.append({'team_country': team1['country'], 'player': player['name'], 'minute': minute, 'gif': gif_url})
    for _ in range(score2):
        player = choose_scorer(team2['players'])
        minute = random_minute()
        gif_local = random.choice(ASSETS['key_moment_gifs'])
        gif_url = get_gif_url(gif_local)
        scorers.append({'team_country': team2['country'], 'player': player['name'], 'minute': minute, 'gif': gif_url})
    winner_id = None
    commentary = ''
    if score1 != score2:
        winner_id = team1['_id'] if score1 > score2 else team2['_id']
    else:
        et1 = poisson_random(0.5)
        et2 = poisson_random(0.5)
        score1 += et1
        score2 += et2
        for _ in range(et1):
            player = choose_scorer(team1['players'])
            gif_local = random.choice(ASSETS['key_moment_gifs'])
            scorers.append({'team_country': team1['country'], 'player': player['name'], 'minute': random_minute(91,120), 'gif': get_gif_url(gif_local)})
        for _ in range(et2):
            player = choose_scorer(team2['players'])
            gif_local = random.choice(ASSETS['key_moment_gifs'])
            scorers.append({'team_country': team2['country'], 'player': player['name'], 'minute': random_minute(91,120), 'gif': get_gif_url(gif_local)})
        if score1 != score2:
            winner_id = team1['_id'] if score1 > score2 else team2['_id']
        else:
            p1, p2 = penalty_shootout()
            if p1 > p2:
                winner_id = team1['_id']
            else:
                winner_id = team2['_id']
            commentary += f"Penalties {p1}-{p2}."
    # generate commentary via OpenAI client if provided
    if openai_client and use_commentary:
        try:
            prompt = f"Generate a concise match summary and 6 short key moments for a football match between {team1['country']} and {team2['country']}. Final score {team1['country']} {score1} - {score2} {team2['country']}. Scorers: "
            for sc in scorers:
                prompt += f"{sc['team_country']} - {sc['player']} ({sc['minute']}') ; "
            resp = openai_client.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[{'role':'system','content':'You are a sports commentator.'},{'role':'user','content':prompt}],
                max_tokens=400,
                temperature=0.7,
            )
            commentary = resp['choices'][0]['message']['content']
        except Exception:
            commentary = commentary

    # Fallback: create a concise commentary summary if no AI commentary produced
    if not commentary:
        parts = []
        parts.append(f"Final score: {team1['country']} {score1} - {score2} {team2['country']}.")
        if scorers:
            # pick up to 6 key moments ordered by minute
            key = sorted(scorers, key=lambda s: s['minute'])[:6]
            moments = []
            for s in key:
                moments.append(f"{s['minute']}' {s['team_country']}: {s['player']}")
            parts.append("Key moments: " + "; ".join(moments) + ".")
        commentary = "\n".join(parts)
    return {
        'score1': score1,
        'score2': score2,
        'scorers': sorted(scorers, key=lambda s: s['minute']),
        'winner_id': winner_id,
        'commentary': commentary,
        'assets': {
            'goal_sfx': ASSETS['goal_sfx'],
            'crowd_cheer': ASSETS['crowd_cheer']
        }
    }

# Helpers

def poisson_random(lam):
    L = pow(2.718281828459045, -lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= random.random()
    return max(0, k-1)

def choose_scorer(players):
    weights = []
    for p in players:
        w = 1
        if p['natural'] == 'AT': w = 5
        elif p['natural'] == 'MD': w = 3
        elif p['natural'] == 'DF': w = 1
        else: w = 0.5
        weights.append(w)
    total = sum(weights)
    r = random.random() * total
    upto = 0
    for i, w in enumerate(weights):
        if upto + w >= r:
            return players[i]
        upto += w
    return players[0]

def random_minute(a=1, b=90):
    return random.randint(a, b)

def penalty_shootout():
    s1 = 0
    s2 = 0
    for _ in range(5):
        if random.random() < 0.75: s1 += 1
        if random.random() < 0.75: s2 += 1
    while s1 == s2:
        if random.random() < 0.75: s1 += 1
        if random.random() < 0.75: s2 += 1
    return s1, s2

# Analytics helper: compute simple stats for a team
def compute_team_stats(team_doc, db):
    # total goals scored in matches
    from bson.objectid import ObjectId
    matches = list(db.matches.find({'$or': [{'team1': team_doc['_id']}, {'team2': team_doc['_id']}], 'played': True}))
    goals_scored = 0
    goals_against = 0
    wins = 0
    losses = 0
    draws = 0
    for m in matches:
        if m['team1'] == team_doc['_id']:
            goals_scored += m.get('score1',0)
            goals_against += m.get('score2',0)
            if m.get('score1') > m.get('score2'): wins += 1
            elif m.get('score1') < m.get('score2'): losses += 1
            else: draws += 1
        else:
            goals_scored += m.get('score2',0)
            goals_against += m.get('score1',0)
            if m.get('score2') > m.get('score1'): wins += 1
            elif m.get('score2') < m.get('score1'): losses += 1
            else: draws += 1
    return {'goals_scored': goals_scored, 'goals_against': goals_against, 'wins': wins, 'losses': losses, 'draws': draws, 'matches_played': len(matches)}

# Top scorers across db
def top_scorers(db, limit=10):
    scorers = {}
    for m in db.matches.find({'played': True}):
        for s in m.get('scorers', []):
            key = (s['team_country'], s['player'])
            scorers[key] = scorers.get(key, 0) + 1
    lst = [{'team': k[0], 'player': k[1], 'goals': v} for k,v in scorers.items()]
    lst.sort(key=lambda x: x['goals'], reverse=True)
    return lst[:limit]

# Seed demo teams

def demo_team(country=None):
    if not country:
        country = random.choice(AFRICAN_COUNTRIES)
    players = [build_player(rand_name(), random.choices(POSITIONS, weights=[0.05,0.4,0.35,0.2])[0]) for _ in range(23)]
    return {
        'country': country,
        'rep_name': rand_name(),
        'rep_email': f"{rand_name().replace(' ','').lower()}@example.com",
        'manager': rand_name(),
        'players': players,
        'rating': team_rating(players),
        'created_at': datetime.utcnow()
    }
