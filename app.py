from flask import Flask, render_template, request, url_for, session, redirect, flash
from pymongo import MongoClient
from codet5 import CodeT5
from scraper import GithubScraper
import urllib.parse
import os
import config
from datetime import datetime, timezone
import shutil
import json
import re

app = Flask(__name__)
app.config.from_object('config.DevConfig')
app.secret_key = "secretkey"

# database config
MONGO_URI = config.MONGO_URI
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is not set!")

client = MongoClient(MONGO_URI)
db = client.get_database('db')
users = db.get_collection('users')
codestorage = db.get_collection('codestorage')

# global variables
files_data = {'repoName':'', 'files':[], 'summary':''}

def fetch_filesdata(username, repo):
    document = codestorage.find_one({"username": username, "repo": repo})
    if document:
        return document.get("filedata", [])
    print('fetch_filesdata returned empty')
    return []

def format_text(code):
    formatted_code = code.replace('\n', '<br>')
    formatted_code = formatted_code.replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
    return formatted_code

@app.route("/test")
def test():
    return "TEST FLASK PAGE. does it render??"

@app.route("/create", methods=["POST", "GET"])
def create():
    if request.method == "POST":
        firstname = request.form.get('first-name')
        lastname = request.form.get('last-name')
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        github_username = request.form.get('github-username')
        if users.find_one({"username" : username}) or users.find_one({'email': email}) or users.find_one({'github_username': github_username}): # user already exists
            flash("User already exists, please choose another", "info")
        else:
            users.insert_one({
                "username" : username,
                "password" : password,
                'email': email,
                'github_username': github_username,
                'firstname': firstname,
                'lastname': lastname,
                'date_created': datetime.now(timezone.utc)
                })
            flash("Account creation successful!", "info")
            return redirect(url_for("login"))
    return render_template("create.html")
        
@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        username = request.form.get('name')
        password = request.form.get('password')
        if (users.find_one({"username" : username})):
            user = users.find_one({"username" : username})
            if user['password'] == password:
                session["user"] = username
                session["mode"] = "dark"

                return redirect(url_for("index"))
            else:
                flash("Invalid username or password. Please try again", "error")

        else:
            flash("Invalid username or password. Please try again", "error")
            
    return render_template("login.html")
    
@app.route("/logout")
def logout():
    session.clear()
    flash("Successfully logged out.", "info")
    return redirect(url_for("login"))


@app.route('/', methods={"GET", "POST"})
def index():        
    if "user" in session:
        #might need to rerun after submitting new inquiry
        cursor = codestorage.find({"username" : session["user"]})
        repos = [a["repo"] for a in cursor]
        if request.method == "POST":
            if "mode" in session:
                session["mode"] = "dark" if session.get("mode") != "dark" else ""
        return render_template('starting.html', repos=repos, mode=session.get("mode"))
    
    else:
        flash("Not logged in yet.", "info")
        return redirect(url_for("login"))
    

@app.route('/gen_pseudo', methods=['GET', "POST"])
def gen_pseudo():
    if "user" in session:
        # might need to rerun after submitting new inquiry

        if request.method == "POST":
            if 'generate_pseudo' in request.form.get('form_name'):
                # files_data['repoName'] = request.form.get('repo')
                files_data['files'] = fetch_filesdata(session["user"], request.form.get('repo'))
                cur_user = session["user"]
                cur_repo = files_data['repoName']
                print(f"index: {request.form.get('index')}")
                print(f"files length: {len(files_data['files'])}")
                if files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] == 'true':
                    files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] = 'false'
                    codestorage.update_one({"username" : cur_user, "repo" : cur_repo}, {"$set" : {f"filedata.{int(request.form.get('index')) - 1}.{'is_toggled'}": 'false'}})

                elif files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] == 'false':
                    files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] = 'true'
                    codestorage.update_one({"username" : cur_user, "repo" : cur_repo}, {"$set" : {f"filedata.{int(request.form.get('index')) - 1}.{'is_toggled'}": 'true'}})

                if files_data['files'][int(request.form.get('index')) - 1]['generate_pseudo'] == 'false':
                    code_t5 = CodeT5()
                    result = code_t5.summarize_line(files_data['files'][int(request.form.get('index')) - 1]['code'])
                    files_data['files'][int(request.form.get('index')) - 1]['pseudo'] = result
                    codestorage.update_one({"username" : cur_user, "repo" : cur_repo}, {"$set" : {f"filedata.{int(request.form.get('index')) - 1}.{'pseudo'}": result}})

                    files_data['files'][int(request.form.get('index')) - 1]['generate_pseudo'] = 'true'
                    codestorage.update_one({"username" : cur_user, "repo" : cur_repo}, {"$set" : {f"filedata.{int(request.form.get('index')) - 1}.{'generate_pseudo'}": 'true'}})

        fileExts = [a["filename"].split(".")[-1] for a in files_data["files"]]
        
        with open('static/json/coding_languages.json', 'r') as f:
            data = json.load(f)
            
        ext_to_name = {ext.strip('.'): entry['name'] for entry in data if 'extensions' in entry for ext in entry['extensions']}
                
        for file_data in files_data['files']:
            filename = file_data['filename']
            file_ext = filename.split('.')[-1] if '.' in filename else 'Unknown'
            file_data['ext'] = file_ext
            file_data['language'] = ext_to_name.get(file_ext, 'Unknown').lower()
            
        cursor = codestorage.find({"username" : session["user"]})
        repos = [a["repo"] for a in cursor]
        cur_repo = files_data['repoName']
        return render_template('searchResults.html', files_data=files_data, repos=repos, cur_repo=cur_repo, mode=session.get("mode"))
    else:
        flash("Not logged in yet.", "info")
        return redirect(url_for("login"))

@app.route('/search', methods=['GET', "POST"])
def search():
    cur_repo = files_data['repoName']
    if "user" in session:
        files_data['repoName'] = ''
        files_data['summary'] = ''
        files_data['files'] = []
        if request.method == "POST":
            if (request.form.get('form_name') == 'query'):
                query = request.form.get('query')
                
                print("query received")
                if query.startswith('http') and 'github.com' in query:
                    scraper = GithubScraper(query)       
                    directory = f'temp_repos/{scraper.owner}_{scraper.repo}'
                    scraper.download_files(directory)
                    files_data['repoName'] = scraper.repo
                    for root, dirs, files in os.walk(directory):
                        for file in files:
                            file_path = os.path.join(root, file)
                            fileName = file[:-4].replace('\\', '/')
                            with open(file_path, 'r', encoding='utf-8') as file_obj:
                                content = []
                                for line in file_obj:
                                    content.append(line)

                                toadd = {'filename': fileName, 'code': content, 'generate_pseudo': 'false', 'pseudo': [], 'is_toggled': 'false'}
                                files_data['files'].append(toadd)
                                
                                
                                cur_user = session["user"]

                                if (codestorage.find_one({"username" : cur_user, "repo" : scraper.repo})):
                                    data = codestorage.find_one({"username" : cur_user, "repo" : scraper.repo})
                                    fileNames = [a["filename"] for a in data["filedata"]]
                                    if fileName not in fileNames:
                                        cur_filedata = data["filedata"]
                                        cur_filedata.append(toadd)
                                        codestorage.update_one({"username" : cur_user, "repo" : scraper.repo, 'github_username': scraper.owner}, {"$set" : {"filedata": cur_filedata}})
                                else:
                                    codestorage.insert_one({"username" : cur_user, "repo" : scraper.repo, 'github_username': scraper.owner, "filedata" : [toadd]})
                                    
                                # delete local storage
                                os.remove(file_path)
                                
                    if os.path.exists(directory):
                        shutil.rmtree(directory)

                    print("finished walking through the entire directory")
                    cur_repo = files_data['repoName']

                else:
                    
                    # extension = get_extension(query)
                    fileName = f'submittedProgram'

                    content = query.splitlines()
                    for i in range(len(content)):
                        content[i] = content[i] + '\n'
                        
                    toadd = {'filename': fileName, 'code': content, 'generate_pseudo': 'false', 'pseudo': [], 'is_toggled': 'false'}
                    files_data['files'].append(toadd)
                    
                    cur_user = session["user"]
                    try:
                        code_t5 = CodeT5()
                        content = []
                        for line in query.splitlines():
                            content.append(line)
                        title = re.split(r'(?<=[.!?])\s+', code_t5.summarize_code(query))[0]
                        repo = " ".join(title.split()[:5]) + '...'
                        files_data['summary'] = title
                    except:
                        repo = query[:8].strip() + '...'
                    
                    cur_repo = repo
                    files_data['repoName'] = repo
                    if (codestorage.find_one({"username" : cur_user, "repo" : repo})):
                        data = codestorage.find_one({"username" : cur_user, "repo" : repo})
                        fileNames = [a["filename"] for a in data["filedata"]]
                        if fileName not in fileNames:
                            cur_filedata = data["filedata"]
                            cur_filedata.append(toadd)
                            codestorage.update_one({"username" : cur_user, "repo" : repo, 'github_username': '', 'summary': files_data['summary']}, {"$set" : {"filedata": cur_filedata}})
                    else:
                        codestorage.insert_one({"username" : cur_user, "repo" : repo, 'github_username': '', "filedata" : [toadd], 'summary': files_data['summary']})
                
        with open('static/json/coding_languages.json', 'r') as f:
            data = json.load(f)
            
        ext_to_name = {ext.strip('.'): entry['name'] for entry in data if 'extensions' in entry for ext in entry['extensions']}
                
        for file_data in files_data['files']:
            filename = file_data['filename']
            file_ext = filename.split('.')[-1] if '.' in filename else 'Unknown'
            file_data['ext'] = file_ext
            file_data['language'] = ext_to_name.get(file_ext, 'Unknown').lower()
                
        cursor = codestorage.find({"username" : session["user"]})
        repos = [a["repo"] for a in cursor]
        
        return render_template('searchResults.html', files_data=files_data, repos=repos, mode=session.get("mode"), cur_repo=cur_repo)
    else:
        flash("Not logged in yet.", "info")
        return redirect(url_for("login"))

@app.route("/<repository>", methods=['POST', 'GET'])
def repo(repository):
    if "user" in session:
        cursor = codestorage.find({"username" : session["user"]})
        repos = [a["repo"] for a in cursor]
        files_data['files'] = fetch_filesdata(session["user"], repository)
        files_data['repoName'] = repository
        print(repository)
        # if request.method == 'POST':
        #     if 'generate_pseudo' in request.form.get('form_name'):
        #         print('generating pseudo for past search')
                
        #         if files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] == 'true':
        #             files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] = 'false'
        #         elif files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] == 'false':
        #             files_data['files'][int(request.form.get('index')) - 1]['is_toggled'] = 'true'
                
        #         if files_data['files'][int(request.form.get('index')) - 1]['generate_pseudo'] == 'false':
        #             code_t5 = CodeT5()
        #             result = code_t5.summarize_by_line(files_data['files'][int(request.form.get('index')) - 1]['code'])
        #             files_data['files'][int(request.form.get('index')) - 1]['pseudo'] = result
        #             files_data['files'][int(request.form.get('index')) - 1]['generate_pseudo'] = 'true'
                    
        #         return render_template('searchResults.html', files_data=files_data, repos=repository)
        # else:
        
        
        with open('static/json/coding_languages.json', 'r') as f:
            data = json.load(f)
            
        ext_to_name = {ext.strip('.'): entry['name'] for entry in data if 'extensions' in entry for ext in entry['extensions']}
                
        for file_data in files_data['files']:
            filename = file_data['filename']
            file_ext = filename.split('.')[-1] if '.' in filename else 'Unknown'
            file_data['ext'] = file_ext
            file_data['language'] = ext_to_name.get(file_ext, 'Unknown').lower()
        
        return render_template('searchResults.html', files_data=files_data, repos=repos, cur_repo = repository, mode=session.get("mode"))
    else:
        flash('Please login first.', 'info')
        return redirect(url_for('login'))
    '''
    if "user" in session:
        if (codestorage.find_one({"username" : session["user"], "repo" : repository})):
            data = codestorage.find_one({"username" : session["user"], "repo" : repository})
            return render_template("pastResults.html", filedata = data["filedata"])
    else:
        return redirect(url_for("index"))
    '''

@app.route("/<repository>/delete")
def delete(repository):
    repo = urllib.parse.unquote(repository)
    if "user" in session:
        cur_user = session["user"]
        codestorage.delete_one({ "username": cur_user, "repo" : repo })
        return redirect(url_for("index"))
    flash("Not logged in yet!", "error")
    return redirect(url_for("login"))



if __name__ == "__main__":
    app.run(debug=True, port=5550)