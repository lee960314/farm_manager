from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import firebase_admin
from firebase_admin import credentials, auth
import os

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

# Google Sheets API 인증 설정
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    os.getenv('GOOGLE_SHEET_KEY_PATH'), scope
)
client = gspread.authorize(creds)

# 스프레드시트 및 시트 설정
spreadsheet_id = os.getenv('SPREADSHEET_ID')
sheet_name = '2024년'
labor_sheet_name = '인건비'
operating_sheet_name = '운영비'
subcontracting_sheet_name = '하청비용'

sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
labor_sheet = client.open_by_key(spreadsheet_id).worksheet(labor_sheet_name)
operating_sheet = client.open_by_key(spreadsheet_id).worksheet(operating_sheet_name)
subcontracting_sheet = client.open_by_key(spreadsheet_id).worksheet(subcontracting_sheet_name)

# Firebase Admin SDK 초기화
firebase_cred = credentials.Certificate(os.getenv('FIREBASE_KEY_PATH'))
firebase_admin.initialize_app(firebase_cred)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        try:
            user = auth.get_user_by_email(user_id)
            session['user'] = user_id  # 사용자 세션 설정
            flash('로그인 성공!', 'success')
            return redirect(url_for('index'))
        except firebase_admin.auth.AuthError:
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

def insert_row(sheet, data):
    try:
        cells = sheet.range('A2:A' + str(sheet.row_count))
        next_row = 2
        for cell in cells:
            if cell.value == '':
                next_row = cell.row
                break
        print(f'Inserting data at row {next_row}: {data}')  # 디버깅용 로그 추가
        sheet.insert_row(data, next_row)
        return True
    except Exception as e:
        print(f'Error inserting data: {e}')
        return False

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
            if field not in data:
                return jsonify({'success': False, 'error': f'{field} is required'}), 400

        # 공통 데이터
        common_data = [
            data.get('date', ''),                  # A 열
            data.get('field', ''),                 # B 열
            data.get('weather', ''),               # C 열
            data.get('temperature', ''),           # D 열
            data.get('humidity', ''),              # E 열
            data.get('rainfall', ''),              # F 열
            data.get('use-fertilizer', 'no'),      # G 열
            data.get('use-remarks', 'no'),         # S 열
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
            # 공통 데이터 반복
            if i % 5 == 0 or i < len(actual_fertilizer_data) or i < len(actual_labor_data):
                row += common_data[:7]
            else:
                row += [''] * 7
            # 비료 데이터
            if i < len(actual_fertilizer_data):
                row += actual_fertilizer_data[i]
            else:
                row += [''] * 5
            # 작업 인력 사용 여부 반복
            if i % 5 == 0 or i < len(actual_fertilizer_data) or i < len(actual_labor_data):
                row.append(data.get('use-labor', 'no'))
            else:
                row.append('')
            # 작업 인력 데이터
            if i < len(actual_labor_data):
                row += actual_labor_data[i]
            else:
                row += [''] * 5
            # 비고 데이터 반복
            if i % 5 == 0 or i < len(actual_fertilizer_data) or i < len(actual_labor_data):
                row += common_data[7:]
            else:
                row += [''] * 2
            rows.append(row)

        # 2행부터 시작하여 빈 행 찾기
        cells = sheet.range('A2:A' + str(sheet.row_count))
        next_row = 2
        for cell in cells:
            if (cell.value == ''):
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

# farmaccounting.html 페이지를 렌더링하는 엔드포인트 추가
@app.route('/farmaccounting', methods=['GET', 'POST'])
def farmaccounting():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        data = request.json
        print('Received farm accounting data:', data)  # 디버깅용 콘솔 로그 추가

        try:
            saved = False

            # 인건비 데이터 수집 및 확인
            for i in range(1, 11):
                labor_data = [
                    data.get('date', ''),              # 날짜
                    data.get(f'labor-type-{i}', ''),      # 인건비 항목
                    data.get(f'labor-currency-{i}', ''),  # 화폐
                    data.get(f'amount-{i}', ''),          # 인원
                    data.get(f'daily-wage-{i}', ''),      # 일당
                    data.get(f'total-{i}', ''),           # 합계
                    data.get(f'labor-remarks-{i}', '')    # 비고
                ]
                print(f'Labor data {i}:', labor_data)  # 디버깅용 로그 추가

                if any(labor_data[1:]):  # 날짜 외의 필드가 존재하는지 확인
                    saved = insert_row(labor_sheet, labor_data) or saved

            # 운영비 데이터 수집 및 확인
            for i in range(1, 11):
                operating_data = [
                    data.get('date', ''),
                    data.get(f'item-{i}', ''),
                    data.get(f'cost-{i}', ''),
                    data.get(f'operating-currency-{i}', ''),
                    data.get(f'operating-remarks-{i}', '')
                ]
                print(f'Operating data {i}:', operating_data)  # 디버깅용 로그 추가

                if any(operating_data[1:]):  # 날짜 외의 필드가 존재하는지 확인
                    saved = insert_row(operating_sheet, operating_data) or saved

            # 하청비용 데이터 수집 및 확인
            for i in range(1, 11):
                subcontracting_data = [
                    data.get('date', ''),
                    data.get(f'task-name-{i}', ''),
                    data.get(f'subcontracting-cost-{i}', ''),
                    data.get(f'subcontracting-currency-{i}', ''),
                    data.get(f'subcontracting-remarks-{i}', '')
                ]
                print(f'Subcontracting data {i}:', subcontracting_data)  # 디버깅용 로그 추가

                if any(subcontracting_data[1:]):  # 날짜 외의 필드가 존재하는지 확인
                    saved = insert_row(subcontracting_sheet, subcontracting_data) or saved

            if not saved:
                return jsonify({'success': False, 'error': 'No data to save or insert failed'})

            return jsonify({'success': True})
        except Exception as e:
            print('Error:', e)
            return jsonify({'success': False, 'error': str(e)})

    return render_template('FarmAccounting.html')

if __name__ == '__main__':
    app.run(debug=True)
