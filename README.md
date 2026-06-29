# NCBI Fungi Genome & Annotation Auto-Downloader

NCBI에서 Fungi(균류, TaxID: 4751)에 속하고 annotation이 완료된 모든 genome 데이터(gff, cds.fasta, faa, fna 등)를 자동으로 수집하고, 매일 새로 업데이트되는 데이터를 주기적으로 동기화하는 백그라운드 파이프라인 시스템입니다.

---

## 주요 기능

1. **JSON 기반 경량 DB (`genomes_metadata.json`)**
   - 별도의 무거운 RDBMS 설치 없이 JSON 파일로 메타데이터와 다운로드 이력을 추적 및 동기화합니다.
   - 파일 쓰기 중 크래시로 인한 손상을 방지하기 위해 **원자적 쓰기(Atomic Write)** 기법을 사용합니다.
2. **Accession 기반 심볼릭 링크 구조**
   - 개별 유전체 원본 폴더(`all_genomes/`)와 별개로, 파일 유형별 수집 폴더(`fna`, `gff`, `cds`, `faa`)를 생성합니다.
   - 디스크 용량 낭비를 차단하기 위해 **Linux 심볼릭 링크(Symbolic Link)** 방식을 채택하며, 링크 파일명을 **`<Accession>.<ext>`**로 매핑하여 Accession 넘버로 즉각적인 개별 서열/어노테이션 탐색이 가능합니다.
3. **NCBI Taxonomy 연동 및 계통별 요약 리포트**
   - 각 유전체의 `taxId`를 통해 NCBI Taxonomy 데이터를 조회하여 문(Phylum), 강(Class), 목(Order) 등의 계통 정보를 로컬 DB에 보관합니다.
   - 파이프라인 가동 완료 시 계층 트리 형태로 다운로드 현황판(`download_overview.txt`)을 자동 갱신합니다.
4. **Linux Cron 스케줄 자동화**
   - 크론 데몬 구동 시 발생할 수 있는 환경변수 누락 에러를 차단해 주는 쉘 래퍼(`run_pipeline.sh`)와 `crontab`에 매일 자동 실행을 스케줄링해 주는 `cron_setup.sh`를 포함합니다.
5. **MD5 체크섬 무결성 검증 및 재시도 파이프라인**
   - 다운로드한 ZIP 패키지 내부의 `md5sum.txt`를 실시간 파싱하여 추출된 파일들의 무결성을 교차 검증합니다.
   - 검증 실패(불일치) 시 **해당 불완전 데이터를 즉시 완전 삭제**하고, 깨끗한 상태에서 최대 3회까지 다운로드 ➔ 압축 해제 ➔ MD5 검증의 재시도(Clean Retry) 루프를 수행합니다.

---

## 배포 및 사용 방법 (WSL / Linux 서버 공통)

### 1. 전제 조건 및 NCBI Datasets CLI 설치
이 시스템은 NCBI 공식 CLI 도구인 `datasets`를 호출하여 데이터를 다운로드합니다. 타겟 리눅스 서버에 아래 명령어로 CLI를 설치해 줍니다.

```bash
# 리눅스 x64용 datasets CLI 다운로드 및 실행 권한 부여
curl -o datasets 'https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/mac/datasets'
chmod +x datasets

# 시스템 PATH 경로로 이동
sudo mv datasets /usr/local/bin/

# 설치가 정상적으로 되었는지 버전 확인
datasets --version
```

### 2. 저장소 복사 (Git Clone)
이 레포지토리를 다른 리눅스 서버의 작업 디렉토리에 클론합니다.

```bash
# 레포지토리 복사
git clone https://github.com/hope9901/fungi-genome-downloader.git
cd fungi-genome-downloader
```

### 3. 환경 변수 및 디렉토리 설정 (선택 사항)
본 프로그램은 기본적으로 사용자 홈 디렉토리 하위의 `~/fungi_project` 폴더에 데이터를 적재하도록 설정되어 있습니다. 
만약 저장 경로를 커스텀하고 싶다면 환경 변수 `FUNGI_PROJECT_ROOT`를 설정하거나 `.env` 파일에 기록하여 구동할 수 있습니다.

```bash
# .env 파일 생성 예시 (필요시 수정)
echo 'FUNGI_PROJECT_ROOT="/var/data/fungi_project"' > .env
```

### 4. 최초 수동 실행 테스트
파이프라인을 수동 실행하여 Fungi 메타데이터 동기화 및 최초 유전체 다운로드가 정상 작동하는지 확인합니다.

```bash
# 파이프라인 실행
python3 main.py
```
*실행 과정에서 발생하는 모든 로깅 내역은 `pipeline.log` 파일에서 상세히 확인하실 수 있습니다.*

### 5. 매일 자동 동기화 스케줄러 등록 (Cron)
NCBI에 매일 새로 Submission되는 균류 데이터를 자동으로 추적하기 위해 Linux의 `cron`에 파이프라인을 등록합니다.

```bash
# cron 셋업 스크립트 실행 (매일 새벽 2시 실행 스케줄로 자동 등록됨)
bash cron_setup.sh

# crontab 등록 내용 확인
crontab -l
```

---

## 수집 후 최종 데이터 디렉토리 구조

동기화가 이루어지면 `FUNGI_PROJECT_ROOT/data/fungi` 경로는 다음과 같이 구조화됩니다.

```text
data/fungi/
├── genomes_metadata.json                             # JSON 데이터베이스 (현황 관리)
├── download_overview.txt                             # 계통별 집계 및 다운로드 종합 현황판
│
├── all_genomes/                                      # 학명_Strain_Accession_레벨 폴더 (원본 소스)
│   └── Saccharomyces_cerevisiae_S288C_GCF_000146045.2_Chromosome/
│       ├── Saccharomyces_cerevisiae_S288C_GCF_000146045.2_Chromosome_genomic.fna
│       ├── Saccharomyces_cerevisiae_S288C_GCF_000146045.2_Chromosome_genomic.gff
│       ├── Saccharomyces_cerevisiae_S288C_GCF_000146045.2_Chromosome_cds.fna
│       └── Saccharomyces_cerevisiae_S288C_GCF_000146045.2_Chromosome_protein.faa
│
├── fna/                                              # Accession 기반 Genome FASTA 링크 폴더
│   └── GCF_000146045.2.fna ➔ ../all_genomes/Saccharomyces_.../Saccharomyces_..._genomic.fna
├── gff/                                              # Accession 기반 GFF 링크 폴더
│   └── GCF_000146045.2.gff ➔ ../all_genomes/Saccharomyces_.../Saccharomyces_..._genomic.gff
├── cds/                                              # Accession 기반 CDS FASTA 링크 폴더
│   └── GCF_000146045.2.fna ➔ ../all_genomes/Saccharomyces_.../Saccharomyces_..._cds.fna
└── faa/                                              # Accession 기반 Protein FASTA 링크 폴더
    └── GCF_000146045.2.faa ➔ ../all_genomes/Saccharomyces_.../Saccharomyces_..._protein.faa
```
