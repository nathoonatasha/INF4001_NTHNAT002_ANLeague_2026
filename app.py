import os
import json
import random
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import utils
import openai
import smtplib
from email.message import EmailMessage

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise RuntimeError('MONGO_URI not set in environment')

client = MongoClient(MONGO_URI)
db = client.anleague

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'adminpass')

SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '0')) if os.getenv('SMTP_PORT') else None
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'dev_secret')

# Ensure admin user exists in db (store hashed)
users = db.users
if not users.find_one({'username': ADMIN_USERNAME}):
    users.insert_one({
        'username': ADMIN_USERNAME,
        'password': generate_password_hash(ADMIN_PASSWORD),
        'role': 'admin'
    })

# Helpers
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# Routes
@app.route('/')
def index():
    teams = list(db.teams.find().sort('created_at', 1))
    return render_template('index.html', teams=teams)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        country = data.get('country')
        rep_name = data.get('rep_name')
        rep_email = data.get('rep_email')
        manager = data.get('manager')
        autofill = data.get('autofill')
        players = []
        if autofill == 'on':
            players = [utils.generate_player(i) for i in range(23)]
        else:
            # parse players from form; expect player-name-N and pos-N
            for i in range(23):
                name = data.get(f'player_name_{i}')
                pos = data.get(f'player_pos_{i}')
                if not name or not pos:
                    continue
                players.append({'name': name, 'natural': pos})
            # ensure captain chosen
        captain_index = int(data.get('captain_index', 0))
        # convert to full player objects with ratings
        full_players = []
        for idx, p in enumerate(players):
            player = utils.build_player(p['name'], p['natural'])
            player['is_captain'] = (idx == captain_index)
            full_players.append(player)
        team = {
            'country': country,
            'rep_name': rep_name,
            'rep_email': rep_email,
            'manager': manager,
            'players': full_players,
            'rating': utils.team_rating(full_players),
            'created_at': datetime.utcnow(),
        }
        # insert team then create representative user
        res = db.teams.insert_one(team)
        team_id = res.inserted_id
        rep_password = data.get('rep_password')
        # create rep user if not exists
        if users.find_one({'username': rep_email}):
            flash('A user with this email already exists. Please login instead.', 'error')
            return redirect(url_for('index'))
        users.insert_one({
            'username': rep_email,
            'password': generate_password_hash(rep_password),
            'role': 'rep',
            'team_id': team_id
        })
        flash('Team registered successfully. You can login as the representative.', 'success')
        return redirect(url_for('index'))
    countries = utils.AFRICAN_COUNTRIES
    return render_template('register.html', countries=countries)

@app.route('/teams')
def list_teams():
    teams = list(db.teams.find().sort('rating', -1))
    return render_template('teams.html', teams=teams)

@app.route('/bracket')
def show_bracket():
    bracket = list(db.matches.find().sort([("field1", 1), ("field2", -1)]))
    # if not created yet but enough teams, show prospective bracket
    matches = list(db.matches.find().sort('created_at', 1))
    return render_template('bracket.html', matches=matches)

@app.route('/match/<match_id>')
def match_view(match_id):
    from bson.objectid import ObjectId
    match = db.matches.find_one({'_id': ObjectId(match_id)})
    if not match:
        flash('Match not found', 'error')
        return redirect(url_for('show_bracket'))
    # populate team info
    t1 = db.teams.find_one({'_id': match['team1']})
    t2 = db.teams.find_one({'_id': match['team2']})
    return render_template('match.html', match=match, team1=t1, team2=t2)

# Admin
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            session['user'] = {'username': username, 'role': user.get('role', 'admin')}
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# Representative auth
@app.route('/rep/login', methods=['GET', 'POST'])
def rep_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users.find_one({'username': username, 'role': 'rep'})
        if user and check_password_hash(user['password'], password):
            team_id = user.get('team_id')
            session['rep'] = {'username': username, 'role': 'rep', 'team_id': str(team_id) if team_id else None}
            return redirect(url_for('rep_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('rep_login.html')

@app.route('/rep/logout')
def rep_logout():
    session.pop('rep', None)
    return redirect(url_for('index'))


def rep_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'rep' not in session:
            return redirect(url_for('rep_login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/rep/dashboard')
@rep_login_required
def rep_dashboard():
    rep = session.get('rep')
    from bson.objectid import ObjectId
    team = None
    matches = []
    if rep and rep.get('team_id'):
        team = db.teams.find_one({'_id': ObjectId(rep['team_id'])})
        matches = list(db.matches.find({'$or': [{'team1': team['_id']}, {'team2': team['_id']}] }).sort('created_at', 1))
    return render_template('rep_dashboard.html', team=team, matches=matches)

@app.route('/admin')
@login_required
def admin_dashboard():
    teams = list(db.teams.find().sort('created_at', 1))
    matches = list(db.matches.find().sort('created_at', 1))
    allow_start = len(teams) >= 8 and len(matches) == 0
    return render_template('admin.html', teams=teams, matches=matches, allow_start=allow_start)

@app.route('/admin/seed', methods=['POST'])
@login_required
def admin_seed():
    # seed 7 demo teams
    seeded = []
    for _ in range(7):
        team = utils.demo_team()
        res = db.teams.insert_one(team)
        seeded.append(team['country'])
    flash('Seeded 7 demo teams: ' + ', '.join(seeded), 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_eighth', methods=['POST'])
@login_required
def admin_add_eighth():
    team = utils.demo_team()
    db.teams.insert_one(team)
    flash('Added 8th team: ' + team['country'], 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/create_rep_users', methods=['POST'])
@login_required
def admin_create_rep_users():
    # create representative user accounts for teams that don't have one
    created = []
    default_password = 'rep123'
    for t in db.teams.find():
        email = t.get('rep_email')
        if not email:
            continue
        if users.find_one({'username': email}):
            continue
        users.insert_one({
            'username': email,
            'password': generate_password_hash(default_password),
            'role': 'rep',
            'team_id': t['_id']
        })
        created.append(email)
    if created:
        flash(f'Created representative accounts for: {", ".join(created)} (password: {default_password})', 'success')
    else:
        flash('No new representative accounts needed', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/simulate_all', methods=['POST'])
@login_required
def admin_simulate_all():
    # simulate all unplayed matches sequentially
    from bson.objectid import ObjectId
    matches = list(db.matches.find({'played': False}).sort('created_at', 1))
    for m in matches:
        t1 = db.teams.find_one({'_id': m['team1']})
        t2 = db.teams.find_one({'_id': m['team2']})
        result = utils.simulate_match(t1, t2, use_commentary=True, openai_client=openai if OPENAI_API_KEY else None)
        db.matches.update_one({'_id': m['_id']}, {'$set': {
            'played': True,
            'score1': result['score1'],
            'score2': result['score2'],
            'scorers': result['scorers'],
            'winner': result['winner_id'],
            'commentary': result.get('commentary',''),
            'played_at': datetime.utcnow()
        }})
    # record tournament if completed
    remaining = db.matches.count_documents({'played': False})
    if remaining == 0:
        # pick latest winner and record tournament
        last_match = db.matches.find_one(sort=[('created_at', -1)])
        if last_match and last_match.get('winner'):
            winner_team = db.teams.find_one({'_id': last_match['winner']})
            tournament_doc = {'winner_id': winner_team['_id'], 'winner_country': winner_team['country'], 'played_at': datetime.utcnow()}
            db.tournaments.insert_one(tournament_doc)
            # notify all representatives that the tournament has completed
            try:
                notify_tournament_results(tournament_doc)
            except Exception as e:
                app.logger.error('Failed to notify representatives about tournament end: %s', e)
    flash('All matches simulated', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/email', methods=['POST'])
@login_required
def admin_email():
    """Trigger sending a tournament summary to all representatives ."""
    # prefer latest recorded tournament if available
    tour = db.tournaments.find_one(sort=[('played_at', -1)])
    if not tour:
        # build a temporary summary from current matches
        tour = {'winner_country': 'TBD', 'played_at': datetime.utcnow()}
    try:
        notify_tournament_results(tour)
        flash(' Tournament summary sent to representatives (or logged).', 'success')
    except Exception as e:
        app.logger.error(' email failed: %s', e)
        flash('Failed to send  email: ' + str(e), 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/analytics')
def analytics():
    teams = list(db.teams.find().sort('created_at', 1))
    enriched = []
    for t in teams:
        stats = utils.compute_team_stats(t, db)
        enriched.append({'country': t['country'], 'rating': t['rating'], 'stats': stats})
    return render_template('analytics.html', teams=enriched)

@app.route('/history')
def history():
    tours = list(db.tournaments.find().sort('played_at', -1))
    return render_template('history.html', tournaments=tours)

@app.route('/leaderboard')
def leaderboard():
    scorers = utils.top_scorers(db, limit=20)
    return render_template('leaderboard.html', scorers=scorers)

@app.route('/admin/remove_team/<team_id>', methods=['POST'])
@login_required
def admin_remove_team(team_id):
    from bson.objectid import ObjectId
    db.teams.delete_one({'_id': ObjectId(team_id)})
    flash('Team removed', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/replace_team/<team_id>', methods=['POST'])
@login_required
def admin_replace_team(team_id):
    from bson.objectid import ObjectId
    new_team = utils.demo_team()
    db.teams.delete_one({'_id': ObjectId(team_id)})
    db.teams.insert_one(new_team)
    flash('Team replaced with ' + new_team['country'], 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/start', methods=['POST'])
@login_required
def admin_start():
    # create bracket using first 8 teams (by created_at)
    teams = list(db.teams.find().sort('created_at', 1).limit(8))
    if len(teams) < 8:
        flash('Need at least 8 teams to start', 'error')
        return redirect(url_for('admin_dashboard'))
    matches = utils.make_bracket(teams)
    # insert matches into db
    for m in matches:
        db.matches.insert_one(m)
    flash('Tournament started (Quarter Finals created)', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/simulate/<match_id>', methods=['POST'])
@login_required
def admin_simulate(match_id):
    from bson.objectid import ObjectId
    match = db.matches.find_one({'_id': ObjectId(match_id)})
    if not match:
        flash('Match not found', 'error')
        return redirect(url_for('admin_dashboard'))
    team1 = db.teams.find_one({'_id': match['team1']})
    team2 = db.teams.find_one({'_id': match['team2']})
    # request commentary when possible (use OPENAI_API_KEY if configured)
    result = utils.simulate_match(team1, team2, use_commentary=True, openai_client=openai if OPENAI_API_KEY else None)
    # store result
    db.matches.update_one({'_id': match['_id']}, {'$set': {
        'played': True,
        'score1': result['score1'],
        'score2': result['score2'],
        'scorers': result['scorers'],
        'winner': result['winner_id'],
        'commentary': result.get('commentary', ''),
        'played_at': datetime.utcnow()
    }})
    # notify teams
    notify_match_result(team1, team2, result)
    flash('Match simulated', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reset', methods=['POST'])
@login_required
def admin_reset():
    # clear matches and reset to quarter finals state
    db.matches.delete_many({})
    flash('Tournament reset', 'success')
    return redirect(url_for('admin_dashboard'))

# Utility: send email notification
def notify_match_result(team1, team2, result):
    subject = f"Match result: {team1['country']} {result['score1']} - {result['score2']} {team2['country']}"
    body = f"Final score: {team1['country']} {result['score1']} - {result['score2']} {team2['country']}\n\nScorers:\n"
    for s in result['scorers']:
        body += f"{s['team_country']}: {s['player']} ({s['minute']}')\n"
    # attempt to use OpenAI commentary if available
    if OPENAI_API_KEY and 'commentary' in result:
        body += '\nMatch commentary:\n' + result['commentary']
    recipients = []
    if team1.get('rep_email'): recipients.append(team1['rep_email'])
    if team2.get('rep_email'): recipients.append(team2['rep_email'])
    if not recipients:
        app.logger.info('No recipients configured for match result')
        return
    if SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS:
        try:
            msg = EmailMessage()
            msg['From'] = SMTP_USER
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            msg.set_content(body)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            app.logger.info('Email notifications sent')
        except Exception as e:
            app.logger.error('Failed to send email: %s', e)
    else:
        app.logger.info('SMTP not configured - printing notification to log')
        app.logger.info('To: %s', recipients)
        app.logger.info(body)


def notify_tournament_results(tournament):
    """Send tournament summary to all team representatives."""
    subject = f"Tournament completed: Winner - {tournament.get('winner_country', 'TBD')}"
    played_at = tournament.get('played_at')
    played_at_str = played_at.strftime('%Y-%m-%d %H:%M UTC') if hasattr(played_at, 'strftime') else str(played_at)

    # build match list
    try:
        matches = list(db.matches.find({'played': True}).sort('played_at', 1))
    except Exception:
        matches = list(db.matches.find({'played': True}))

    body_lines = [f"Tournament finished on: {played_at_str}", f"Winner: {tournament.get('winner_country', 'TBD')}", "", "Matches:"]
    for m in matches:
        t1 = db.teams.find_one({'_id': m.get('team1')})
        t2 = db.teams.find_one({'_id': m.get('team2')})
        t1name = t1.get('country') if t1 else m.get('team1_country', 'Team1')
        t2name = t2.get('country') if t2 else m.get('team2_country', 'Team2')
        score1 = m.get('score1', 0)
        score2 = m.get('score2', 0)
        body_lines.append(f"- {t1name} {score1} - {score2} {t2name}")
        # include scorers if present
        sc = m.get('scorers', [])
        if sc:
            sc_lines = []
            for s in sc:
                sc_lines.append(f"{s.get('minute','?')}' {s.get('team_country','')}: {s.get('player','')}")
            body_lines.append("  Scorers: " + "; ".join(sc_lines))

    body = "\n".join(body_lines)

    # collect recipient emails from teams
    recipients = []
    for t in db.teams.find():
        email = t.get('rep_email')
        if email and email not in recipients:
            recipients.append(email)

    if not recipients:
        app.logger.info('No representative emails configured for tournament notification')
        return

    if SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS:
        try:
            msg = EmailMessage()
            msg['From'] = SMTP_USER
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            msg.set_content(body)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            app.logger.info('Tournament notification emails sent to representatives')
        except Exception as e:
            app.logger.error('Failed to send tournament emails: %s', e)
    else:
        app.logger.info('SMTP not configured - printing tournament notification to log')
        app.logger.info('To: %s', recipients)
        app.logger.info(body)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)