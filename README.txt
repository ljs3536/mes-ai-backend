MES AI Backend
==============

부품/설비 가공 공장 MES Core API (FastAPI + SQLAlchemy 2 + MariaDB).

지금 코드의 시나리오: 자재 입고(LOT 발행) → 작업지시 → 작업 시작(WIP) → 설비 가공/진행 보고 → 가공 완료(PROCESSED) → 품질 판정 → 출하 → 이력 추적.
AI 이상감지는 services.hold_machine()을 호출한다. 아래 "개선 로직"은 아직 코드에 없고, 그 함수가 설비 정지만 하도록 바꿀 때의 기준이다.

실행 방법과 포트는 작업 폴더의 README.md를 본다.
화면 주소는 MES http://localhost:3000 , 센서 분석 http://localhost:3001 , API 문서 http://localhost:8000/docs 이다.


구조
----
app/
  main.py        앱, 헬스체크(/healthz, /readyz), 라우터 등록
  config.py      환경변수 (DATABASE_URL, CORS_ORIGINS, SEED_DEMO, MQTT_*)
  mqtt_bridge.py MQTT 구독/발행 (IoT-Ingestion으로 분리할 경계)
  gateway.py     센서/PLC 상태 저장, 완료 처리
  models.py      SQLAlchemy 모델
  schemas.py     Pydantic 스키마 (응답은 camelCase)
  services.py    상태 전이 트랜잭션 로직
  queries.py     조회 로직
  routers/       /api/lots, /api/work-orders, /api/machines, /api/dashboard ...
  seed.py        데모 데이터 (빈 DB일 때만)


설비 연동 (MQTT)
----------------
PLC는 mes-ai-edge-gateway가 Modbus TCP로 제어하고,
센서는 mes-ai-machine-emulator가 MQTT로 직접 발행한다.
백엔드는 공유 구독($share/mes-backend/...)을 써서 레플리카를 늘려도 메시지를 한 번만 처리한다.

토픽                                    방향              QoS              내용
mes/machines/{code}/sensors             센서 → MES        0                {"ts", "values": [{"code","value","unit"}]} → sensor_readings 저장
mes/machines/{code}/state               게이트웨이 → MES  0                {"plcOnline","state","workOrderId","producedQty",...} → 진행수량·온라인 갱신
mes/machines/{code}/events              게이트웨이 → MES  1                {"type":"job_completed","workOrderId","producedQty"} → 작업지시 COMPLETED, LOT PROCESSED
mes/machines/{code}/job                 MES → 게이트웨이  1, retained      {"job": {workOrderId, woNo, quantity, producedQty, ...} | null} 목표 작업

- 작업 시작/정지/재개/품질판정 시 job을 다시 발행하고, 진행 중에는 producedQty를 5초마다 갱신한다.
  PLC가 재시작돼도 게이트웨이가 이어서 가공한다.
- 센서값은 sensor_code/value/unit 형태로 저장되므로 센서를 추가해도 스키마 변경이 없다.
- PLC 상태가 MACHINE_OFFLINE_AFTER_SECONDS(기본 10초) 동안 오지 않으면 화면에 오프라인으로 표시된다.
- 최근 센서 원시값: GET /api/machines/{id}/telemetry?minutes=5


로컬 실행
---------
docker run -d --name mes-db -p 3306:3306 \
  -e MARIADB_DATABASE=mes -e MARIADB_USER=mes -e MARIADB_PASSWORD=mes -e MARIADB_ROOT_PASSWORD=root \
  mariadb:11.4
docker run -d --name mes-mqtt -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload


컨테이너
--------
docker build -t factory-mes/backend .
docker run -p 8000:8000 -e DATABASE_URL=mysql+pymysql://mes:mes@<db>:3306/mes?charset=utf8mb4 factory-mes/backend

테이블은 기동 시 create_all로 생성한다. Kubernetes 다중 레플리카로 갈 때 Alembic 마이그레이션(Job)으로 전환할 예정이다.


개선 로직
=========
입고, 작업지시, 가공, 품질, 출하, 이력 화면과 LOT, 작업지시, 설비, 검사, 출하 테이블은 그대로 둔다.
바꾸는 것은 상태 전이뿐이다.

- 설비 정지는 가공을 잠시 멈추는 일이고, 품질 보류는 검사 불합격이다.
- 재개는 같은 작업지시를 이어서 가공한다.
- 출하 수량은 입고 수량이 아니라 가공이 끝난 수량이다.
- 지시 수량이 입고 수량보다 적으면, 시작한 수량만 가공중으로 가고 나머지는 원자재로 남는다.

자재 마스터, 다공정 라우팅, 불량 수량 입력, 로그인, k3s는 이번 개선에 넣지 않는다.


상태
----
LOT
  RAW        원자재. 작업지시에 쓸 수 있다.
  WIP        가공중. 설비가 멈춰 있어도 품질 보류가 아니다.
  PROCESSED  가공 완료. 품질 검사 대기.
  HOLD       품질 불합격. 위치는 품질대기.
  IN_STOCK   합격. 위치는 완제품창고. 수량은 가공 완료 수량.
  SHIPPED    출하 완료.

작업지시
  PLANNED      시작 전. 이 상태만 취소할 수 있다. 행은 지우지 않는다.
  IN_PROGRESS  가공중.
  HOLD         설비 정지로 일시정지. LOT는 WIP.
  COMPLETED    목표 수량 가공 완료.
  CANCELLED    시작 전 취소.

설비
  IDLE  작업 없음.
  RUN   가공중.
  STOP  수동 정지, AI 이상, 또는 점검 대기. 진행 중이던 지시는 HOLD, LOT는 WIP.
  한 설비의 진행 작업은 하나다. RUN 또는 STOP인 설비에는 다른 작업을 시작하지 않는다.


수량
----
입고 수량은 LOT에 남는다.
작업지시 수량은 그 LOT의 남은 RAW 수량 이하다.
작업 시작 시 지시 수량만 WIP로 넘어간다. 입고 수량이 더 크면 남은 수량은 새 RAW LOT로 남고, 같은 자재명을 잇는다.
설비(PLC)가 올린 완료 수량이 생산 수량이다. 목표 수량을 넘기지 않는다.
이번 개선에는 불량 입력 화면이 없다. 합격 수량은 생산 수량과 같다.
출하는 IN_STOCK 수량을 한 번에 내보낸다. 그 수량은 입고 수량이 아니라 생산 수량이다.


전이
----
1. 입고
   품명과 수량을 받으면 LOT 번호 RAW-YYYYMMDD-NNN을 발행한다.
   상태 RAW, 위치 자재창고.

2. 작업지시 발행
   RAW LOT, 설비 한 대, 제품명, 지시 수량.
   상태 PLANNED.
   지시 수량이 남은 RAW보다 크면 거절한다.

3. 작업 시작
   PLANNED 지시만 시작한다.
   작업자를 고른다.
   설비가 IDLE일 때만 시작한다.
   지시 IN_PROGRESS, 설비 RUN, 해당 수량 LOT는 WIP, 위치는 설비 이름.
   남은 RAW가 있으면 별도 RAW LOT로 남는다.
   MES가 목표 작업을 게이트웨이에 내리고, 게이트웨이가 PLC를 그 수량까지 가공시킨다.

4. 가공 중
   PLC가 생산 수량을 올린다.
   목표 수량에 닿으면 게이트웨이가 완료를 알린다.
   지시 COMPLETED, 설비 IDLE, LOT PROCESSED, 위치 검사대기장.

5. 설비 정지 (작업자 또는 AI)
   진행 중(IN_PROGRESS) 작업이 있을 때만 된다.
   설비 STOP, 지시 HOLD, LOT는 WIP를 유지한다. 위치는 설비에 둔다.
   품질 화면의 검사 대상이 되지 않는다.
   경보를 남긴다.

6. 재개
   STOP 설비만 재개한다.
   일시정지(HOLD) 지시를 다시 IN_PROGRESS로 두고 설비는 RUN.
   LOT는 WIP.
   생산 수량 다음부터 가공을 잇는다.
   열린 경보는 확인 처리한다.

7. 시작 전 취소
   PLANNED만 취소한다.
   상태 CANCELLED. 번호는 다시 쓰지 않는다.
   LOT는 RAW 그대로다.

8. 품질 판정
   PROCESSED만 판정한다. WIP와 설비 정지 상태는 판정하지 않는다.
   합격: LOT IN_STOCK, 위치 완제품창고, 수량은 생산 수량.
   불합격: LOT HOLD, 위치 품질대기. 설비는 멈추지 않는다. 작업지시는 COMPLETED를 유지한다.
   메모는 검사 기록에 남긴다.
   재작업, 폐기, 부분 합격은 이번 범위 밖이다. 불합격 LOT는 출하할 수 없다.

9. 출하
   IN_STOCK만 출하한다.
   출하 번호 SHP-YYYYMMDD-NNN.
   수량은 그 LOT의 현재 수량(생산 수량)이다.
   상태 SHIPPED, 위치 출하완료.

이력 추적에는 입고, 작업지시, 시작, 분할이 있었으면 분할, 정지, 재개, 완료, 품질, 출하가 LOT 번호로 이어진다.


사용자 실행 단계
----------------
사전 조건: infra에서 docker compose up 이 끝나 있고, 설비 에뮬레이터와 게이트웨이가 떠 있다.
MES 화면 http://localhost:3000 을 연다.

1. 자재 입고
   메뉴 자재 입고.
   원자재 품목과 수량을 넣고 LOT 발행.
   목록에 RAW LOT 번호가 보인다. 이 번호를 적어두면 마지막에 이력 조회에 쓴다.

2. 작업지시
   메뉴 작업지시.
   원자재 LOT, 설비, 제품명, 지시 수량을 넣고 작업지시 발행.
   지시 수량은 LOT 수량 이하로 한다.
   시작 전이면 사유를 적고 취소할 수 있다. 취소한 지시는 다시 시작되지 않는다.

3. 작업 시작
   같은 작업지시 화면의 작업 시작.
   방금 발행한 지시와 작업자를 고르고 작업 시작.
   LOT는 WIP가 된다.
   지시 수량이 입고 수량보다 적었으면, 자재 입고 목록에 남은 수량의 RAW LOT가 하나 더 있다.

4. 가공 확인
   메뉴 가공 라인.
   해당 설비가 RUN이고 통신 정상인지 본다.
   생산 수량이 지시 수량까지 올라가면 설비는 IDLE, LOT는 가공완료(PROCESSED)가 된다.
   에뮬레이터는 약 0.6초마다 1개씩 올린다. 수량이 크면 끝날 때까지 이 화면을 두면 된다.

5. 중간에 설비를 멈추는 경우
   가공 라인에서 설비가 RUN일 때 설비 정지를 누른다.
   설비는 STOP, 작업지시는 일시정지, LOT는 가공중(WIP)이다.
   품질 검사 목록에는 나오지 않는다.
   점검 후 재개를 누른다.
   설비는 다시 RUN이고, 생산 수량은 멈추기 전 값에서 이어진다.
   AI 이상 감지로 자동 정지된 경우도 같다. 품질 보류가 아니므로 재개로 가공을 잇는다.

6. 품질 검사
   가공이 끝난 뒤 메뉴 품질 검사.
   대상은 가공완료(PROCESSED) LOT뿐이다.
   합격이면 완제품(IN_STOCK), 불합격이면 품질대기(HOLD)다.
   불합격 LOT는 출하 목록에 나오지 않는다.

7. 출하
   메뉴 출하.
   완제품 LOT를 고르고 출하 확정.
   수량은 입고 때 수량이 아니라 그 LOT의 생산 수량이다.
   상태는 출하(SHIPPED)가 된다.

8. 이력 확인
   메뉴 이력 추적.
   1단계에서 받은 LOT 번호를 조회한다.
   입고부터 출하까지의 이벤트가 시간순으로 보여야 한다.
   5단계를 거쳤으면 정지와 재개가 품질 판정보다 앞에 있고, LOT가 그때 HOLD로 바뀌지 않았어야 한다.

센서 분석은 선택이다.
http://localhost:3001 에서 설비에 연결된 센서 파형을 본다.
실시간 적용이 켜진 모델이 이상을 연속으로 판정하면 5단계와 같이 설비만 정지한다.
모델 학습과 파라미터 변경은 분석 화면의 모델 메뉴에서 한다.


지금 코드와의 차이
------------------
아래는 아직 코드에 없다. 이 문서의 개선 로직이 구현 기준이다.

- 설비 정지가 LOT를 품질 HOLD로 보낸다.
- 재개는 설비를 IDLE로만 두고 작업지시 HOLD를 풀어 가공을 잇지 않는다.
- 품질 판정이 가공중 LOT에도 가능하다.
- 출하 수량이 입고 수량이다.
- 지시 수량이 적어도 LOT 전체가 WIP로 바뀌고 잔량 RAW가 남지 않는다.
