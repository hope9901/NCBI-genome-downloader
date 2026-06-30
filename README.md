# NCBI Genome Downloader (범용 멀티-계통 유전체 다운로더)

NCBI Datasets API 및 CLI를 활용하여 **식물(Plants), 균류(Fungi), 세균(Bacteria), 동물(Metazoa) 등 모든 생명체 계통군**의 유전체 어셈블리 데이터를 자동으로 대량 다운로드하고 구조화하는 범용 파이프라인 시스템입니다.

다중 스레드 기반 병렬 전송과 MD5 무결성 검증, 데이터 손상 시 자동 재시도(Clean Retry), 그리고 자체 어노테이션(Re-annotation) 파이프라인 연동 설계가 탑재되어 대용량 유전체 뱅크 구축에 최적화되어 있습니다.

---

## 🌟 주요 기능

1. **범용 계통군(Taxon) 동적 지원**
   - `.env` 설정 파일에서 타겟 계통명(예: `Fungi`, `Viridiplantae`, `Bacteria` 등)만 변경하면, 어떠한 생명체군이든 자동으로 식별하여 다운로드합니다.
2. **계통군별 격리 및 구조화**
   - 여러 계통군의 데이터를 교차 다운로드받더라도, 데이터와 데이터베이스가 지정한 계통명 소문자 폴더(`data/<taxon_name.lower()>/`) 하위에 각각 엄격하게 격리되어 적재되므로 데이터 꼬임이 없습니다.
3. **병렬 멀티스레딩 다운로드 엔진 (`ThreadPoolExecutor`)**
   - 다중 CPU 코어 환경에서 파일 전송 속도를 극대화합니다. 여러 스레드가 동시 다발적으로 데이터베이스에 쓸 때 생길 수 있는 파일 오손을 차단하기 위해 **Thread Lock** 메커니즘을 적용했습니다.
4. **MD5 체크섬 무결성 검증 및 재시도 루프**
   - 다운로드 완료 후 동봉된 `md5sum.txt` 기반으로 압축 해제된 실제 파일들을 실시간 교차 검증합니다.
   - 단 하나의 파일이라도 무결성에 실패할 경우, **해당 불완전 데이터를 즉시 완전 삭제**하고 최대 3회까지 클린 재시도(Clean Retry)를 진행합니다.
5. **자체 어노테이션(Re-annotation) 구조 설계**
   - 다운로드된 개별 유전체 폴더 내부에 `ncbi/` (NCBI 원본) 및 `custom/` (자체 분석 결과) 서브폴더를 기본 탑재합니다.
   - 원본 어노테이션이 아예 제공되지 않았던 유전체(`ncbi.has_annotation: 0`) 여부를 DB가 정밀 추적하므로, 추후 자체 개발한 어노테이션 파이프라인의 타겟 큐로 간편하게 활용할 수 있습니다.
6. **GenBank / RefSeq (GCA / GCF) 파트너 정보 기록**
   - 동일 유전체이나 GCA와 GCF로 다중 등록된 어셈블리들의 1대1 상호 매핑을 위해, 파트너 Accession 정보(`paired_accession`)를 DB에 유기적으로 기입합니다. (동일 서열이라도 어노테이션 유전자 이름 등이 미묘하게 다를 수 있으므로 두 파일 모두 독립된 물리 디렉토리에 온전히 다운로드받습니다).
7. **NCBI API Key 연동**
   - 다중 스레드 가동 시 발생하기 쉬운 NCBI 서버의 일시적 IP 차단(Rate Limit)을 예방할 수 있도록 API Key 연동을 정식 지원합니다.
8. **계통 분류별 탐색 디렉토리 자동 생성 (`taxonomy/`)**
   - 다운로드 완료 시, 각 유전체의 **계(Kingdom) ➔ 문(Phylum) ➔ 강(Class) ➔ 목(Order) ➔ 과(Family) ➔ 속(Genus)** 6단계 계통 분류 수준에 맞게 자동으로 `taxonomy/` 폴더 트리를 빌드합니다.
   - 중간 아랭크(Subclass, Suborder 등)는 표준 6대 분류 뎁스 유지를 위해 필터링 처리하며, 수집 중 누락되거나 비어 있는 분류 단계는 자동으로 **`Unknown_<Rank_Name>`** (예: `Unknown_Class`) 임시 폴더를 주입하여 6단계 폴더 깊이를 깨짐 없이 유지합니다.
   - 해당 속(Genus) 폴더 하위에 실제 유전체 원본 폴더(`all_genomes/...`)를 가리키는 **디렉토리 레벨 상대 경로 심볼릭 링크**를 자동 생성하여 계통학적 탐색 환경을 제공합니다.

---

## 📂 폴더 구조 설계 (`TARGET_TAXON="Viridiplantae"` 구동 예시)

```text
ncbi_project/
├── pipeline.log                                      # 파이프라인 전체 구동 로그
├── run_pipeline.sh                                   # Cron 스케줄러용 실행 래퍼
│
└── data/
    └── viridiplantae/                                # [식물계] 계통별 독립 격리 폴더
        ├── genomes_metadata.json                     # 식물군 전용 JSON 데이터베이스
        ├── download_overview.txt                     # 식물군 다운로드 종합 현황판
        │
        ├── all_genomes/                              # 물리 데이터 디렉토리
        │   └── Populus_trichocarpa_GCF_002013855.1/
        │       ├── ncbi/                             # NCBI 원본 보관소
        │       │   ├── ..._genomic.fna, ..._genomic.gff, ..._cds.fna, ..._protein.faa
        │       └── custom/                           # 자체 파이프라인 결과 보관소 (실행 시 생성)
        │
        ├── taxonomy/                                 # [신설] 6단계 계통학적 탐색 디렉토리
        │   └── Viridiplantae/                        # [계, Kingdom]
        │       └── Streptophyta/                     # [문, Phylum]
        │           └── Magnoliopsida/                # [강, Class]
        │               └── Malpighiales/             # [목, Order]
        │                   └── Salicaceae/           # [과, Family]
        │                       └── Populus/          # [속, Genus]
        │                           └── Populus_trichocarpa_GCF_002013855.1 ➔ ../../../../../../../all_genomes/Populus_trichocarpa_GCF_002013855.1/
        │
        ├── fna/
        │   └── ncbi/ ➔ ../all_genomes/.../ncbi/..._genomic.fna (Accession 기반 심볼릭 링크)
        ├── gff/
        │   └── ncbi/ ➔ ../all_genomes/.../ncbi/..._genomic.gff
        ├── cds/
        │   └── ncbi/ ➔ ../all_genomes/.../ncbi/..._cds.fna
        └── faa/
            └── ncbi/ ➔ ../all_genomes/.../ncbi/..._protein.faa
```

---

## 🛠️ 배포 및 사용 방법 (Linux / WSL 공통)

### 1. 전제 조건 및 NCBI Datasets CLI 설치
NCBI 공식 CLI 도구를 타겟 서버에 설치하고 실행 권한을 부여합니다.

```bash
# 리눅스 x64용 datasets 및 dataformat CLI 다운로드
curl -o datasets 'https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/datasets'
curl -o dataformat 'https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/dataformat'

# 실행 권한 부여 및 시스템 PATH 경로로 이동
chmod +x datasets dataformat
sudo mv datasets dataformat /usr/local/bin/

# 설치 확인
datasets --version
dataformat --version
```

### 2. 저장소 복사 (Git Clone)
```bash
git clone https://github.com/hope9901/NCBI-genome-downloader.git
cd NCBI-genome-downloader
```

### 3. 환경 변수 구성 (`.env` 파일 설정)
프로젝트 설치 디렉토리에 `.env` 파일을 생성하고 다운로드하고자 하는 생명체 계통군(Taxon) 정보 및 다운로드 설정을 자유롭게 설정합니다.

```bash
cat <<EOF > .env
# 다운로드한 데이터를 적재할 전체 프로젝트 루트 폴더 (생략 시 기본값: ~/ncbi_project)
NCBI_PROJECT_ROOT="~/ncbi_project"

# datasets CLI 바이너리가 들어있는 디렉토리 경로 (사용자 서버의 실제 datasets 경로)
NCBI_DATASETS_PATH="~/ncbi_datasets"

# 다운로드 타겟 계통명 (Fungi, Viridiplantae, Bacteria, Metazoa, Mammalia 등 자유롭게 지정)
NCBI_TARGET_TAXON="Viridiplantae"

# NCBI 공식 API 키 (미기재 시 초당 3회, 기재 시 초당 10회 요청으로 제한이 대폭 완화됩니다)
NCBI_API_KEY="your_ncbi_api_key_here"

# 병렬 실행할 다운로드 스레드 개수 (API Key 미등록 시 4, 등록 시 8~15개 추천)
NCBI_PARALLEL_WORKERS=10

# 개별 다운로드 스레드 기동 간 API 호출 지연시간 (초)
NCBI_API_DELAY=0.3
EOF
```

### 4. 파이프라인 구동
```bash
# 뼈대 메타데이터 동기화 및 동시 다운로드 시작 (Lazy Taxonomy 기법으로 딜레이 없이 즉시 개시)
python3 main.py
```

### 5. Cron 스케줄러 등록 (자동 주기 업데이트)
매일 자정/새벽 시간대에 새로운 신규 유전체(NCBI에 새로 릴리즈된 데이터)가 자동으로 유입되어 보완되도록 리눅스 `crontab`에 등록합니다.

```bash
# 실행 권한 부여
chmod +x run_pipeline.sh cron_setup.sh

# 크론 셋업 스크립트 실행 (매일 새벽 2시 자동 업데이트 자동 등록)
./cron_setup.sh
```

---

## 📊 현황 모니터링 (`download_overview.txt`)
파이프라인이 기동되거나 가동 중일 때, 지정한 계통 디렉토리 내에 계통 구조별(문 ➔ 강) 다운로드 통계 및 상세 현황을 텍스트 리포트(`download_overview.txt`) 형태로 실시간 갱신합니다.
* NCBI에서 제공하는 어노테이션이 없는 유전체는 `NCBI Ann: N`으로 표기되어 추후 자체 가동할 `Custom` 어노테이션의 주요 마커가 됩니다.
