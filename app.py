from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import firebase_admin
from firebase_admin import credentials, auth
import os
from dotenv import load_dotenv

app = Flask(__name__)

# .env 파일 경로 설정 및 환경 변수 로드
dotenv_path = os.path.join(os.path.dirname(__file__), 'key.env')
load_dotenv(dotenv_path=dotenv_path)

app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

# Google Sheets API 인증 설정
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    os.path.join(os.path.dirname(__file__), os.getenv('GOOGLE_SHEET_KEY_PATH')), scope
)
client = gspread.authorize(creds)

# 스프레드시트 및 시트 설정
spreadsheet_id = os.getenv('SPREADSHEET_ID')
sheet_name = '2024년'
sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

# Firebase Admin SDK 초기화
firebase_cred = credentials.Certificate(os.path.join(os.path.dirname(__file__), os.getenv('FIREBASE_KEY_PATH')))
firebase_admin.initialize_app(firebase_cred)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        try:
            user = auth.get_user_by_email(user_id)
            # Firebase Authentication에서 비밀번호 확인 로직 추가
            # 클라이언트 측에서 로그인 후 토큰을 받아와서 서버에서 검증하는 방식이 일반적입니다.
            # token = request.form['token']
            # decoded_token = auth.verify_id_token(token)
            session['user'] = user_id  # 사용자 세션 설정
            flash('로그인 성공!', 'success')
            return redirect(url_for('index'))
        except firebase_admin.exceptions.FirebaseError:
            flash('로그인 실패. 사용자 ID 또는 비밀번호를 확인하세요.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('로그아웃되었습니다.', 'success')
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/farmdata', methods=['POST'])
def farmdata():
    if 'user' not in session:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'}), 401
    data = request.json
    print('Received data:', data)  # 디버깅용 콘솔 로그 추가
    try:
        # 데이터 유효성 검사
        required_fields = ['date', 'field', 'weather', 'temperature', 'humidity', 'rainfall', 'use-fertilizer', 'use-remarks', 'remark-text']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'error': f'{field} is required'}), 400

        # 공통 데이터
        common_data = [
            data.get('date', ''),                  # A 열
            data.get('field', ''),                 # B 열
            data.get('weather', ''),               # C 열
            data.get('temperature', ''),           # D 열
            data.get('humidity', ''),              # E 열
            data.get('rainfall', ''),              # F 열
            data.get('use-fertilizer', ''),        # G 열
            data.get('use-remarks', ''),           # S 열
            data.get('remark-text', '')            # T 열
        ]

        # 비료 데이터
        fertilizer_data = [
            [
                data.get(f'fertilizer-type-{i}', ''),
                data.get(f'product-name-{i}', ''),
                data.get(f'amount-{i}', ''),
                data.get(f'method-{i}', ''),
                data.get(f'ratio-{i}', '')
            ]
            for i in range(1, 7)
        ]

        # 작업 인력 데이터
        labor_data = [
            [
                data.get(f'labor-time-{i}', ''),
                data.get(f'labor-amount-{i}', ''),
                data.get(f'labor-task-{i}', ''),
                data.get(f'labor-result-{i}', ''),
                data.get(f'labor-manager-{i}', '')
            ]
            for i in range(1, 7)
        ]

        # 비료/농약과 작업 인력 데이터의 실제 길이 확인
        actual_fertilizer_data = [x for x in fertilizer_data if any(x)]
        actual_labor_data = [x for x in labor_data if any(x)]

        # 세트 단위로 데이터 계산
        num_fertilizer_sets = max(1, (len(actual_fertilizer_data) + 4) // 5)  # 최소 1세트
        num_labor_sets = max(1, (len(actual_labor_data) + 4) // 5)  # 최소 1세트
        max_sets = max(num_fertilizer_sets, num_labor_sets)

        rows = []
        for i in range(max_sets * 5):
            row = []
            # 공통 데이터
            if i % 5 == 0:
                row += common_data[:7]
            else:
                row += [''] * 7
            # 비료 데이터
            if i < len(actual_fertilizer_data):
                row += actual_fertilizer_data[i]
            else:
                row += [''] * 5
            # 작업 인력 사용 여부
            if i % 5 == 0:
                row.append(data.get('use-labor', ''))
            else:
                row.append('')
            # 작업 인력 데이터
            if i < len(actual_labor_data):
                row += actual_labor_data[i]
            else:
                row += [''] * 5
            # 비고 데이터
            if i % 5 == 0:
                row += common_data[7:]
            else:
                row += [''] * 2
            rows.append(row)

        # 2행부터 시작하여 빈 행 찾기
        cells = sheet.range('A2:A' + str(sheet.row_count))
        next_row = 2
        for cell in cells:
            if cell.value == '':
                next_row = cell.row
                break

        # 데이터 추가
        print('Inserting rows at:', next_row)  # 디버깅용 콘솔 로그 추가
        for row in rows:
            print('Inserting row:', row)  # 디버깅용 로그 추가
            sheet.insert_row(row, next_row)
            next_row += 1

        return jsonify({'success': True})
    except Exception as e:
        print('Error:', e)
        return jsonify({'success': False, 'error': str(e)})

# Google Sheets에서 데이터를 가져와 프론트엔드로 전달하는 엔드포인트 추가
@app.route('/getdata', methods=['GET'])
def getdata():
    if 'user' not in session:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'}), 401
    try:
        records = sheet.get_all_records()
        return jsonify({'success': True, 'data': records})
    except Exception as e:
        print('Error:', e)
        return jsonify({'success': False, 'error': str(e)})

# searchdata.html 페이지를 렌더링하는 엔드포인트 추가
@app.route('/searchdata')
def searchdata():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('searchdata.html')

if __name__ == '__main__':
    app.run(debug=True)
