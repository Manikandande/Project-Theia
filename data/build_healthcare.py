"""
Build healthcare.db — a dummy healthcare data mart for Theia.

Run once:
    python3 data/build_healthcare.py

Tables
------
Facility · Provider · Payer · Patient · Insurance
Diagnosis · Procedure · Medication · LabTest
Encounter · EncounterDiagnosis · EncounterProcedure
Claim · Prescription · LabResult
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
DB_PATH = Path(__file__).parent / "healthcare.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def rand_date(start: date, end: date) -> str:
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()

def rand_phone() -> str:
    return f"({random.randint(200,999)}) {random.randint(200,999)}-{random.randint(1000,9999)}"

def rand_npi() -> str:
    return str(random.randint(1_000_000_000, 9_999_999_999))


# ── Reference data ────────────────────────────────────────────────────────────

FIRST_NAMES_M = ["James","John","Robert","Michael","William","David","Joseph","Thomas",
                  "Charles","Christopher","Daniel","Matthew","Anthony","Donald","Mark",
                  "Paul","Steven","Andrew","Kenneth","Joshua","Kevin","Brian","George","Edward"]
FIRST_NAMES_F = ["Mary","Patricia","Jennifer","Linda","Barbara","Elizabeth","Susan","Jessica",
                  "Sarah","Karen","Lisa","Nancy","Betty","Margaret","Sandra","Ashley","Dorothy",
                  "Kimberly","Emily","Donna","Michelle","Carol","Amanda","Melissa","Deborah"]
LAST_NAMES    = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
                  "Rodriguez","Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson",
                  "Thomas","Taylor","Moore","Jackson","Martin","Lee","Perez","Thompson","White",
                  "Harris","Sanchez","Clark","Ramirez","Lewis","Robinson","Walker","Young","Allen"]

CITIES_STATES = [
    ("New York","NY"),("Los Angeles","CA"),("Chicago","IL"),("Houston","TX"),
    ("Phoenix","AZ"),("Philadelphia","PA"),("San Antonio","TX"),("San Diego","CA"),
    ("Dallas","TX"),("San Jose","CA"),("Austin","TX"),("Jacksonville","FL"),
    ("Fort Worth","TX"),("Columbus","OH"),("Charlotte","NC"),("Indianapolis","IN"),
    ("San Francisco","CA"),("Seattle","WA"),("Denver","CO"),("Nashville","TN"),
]

BLOOD_TYPES   = ["A+","A-","B+","B-","AB+","AB-","O+","O-"]
SPECIALTIES   = ["Internal Medicine","Cardiology","Orthopedics","Pediatrics",
                  "Neurology","Oncology","Gastroenterology","Pulmonology",
                  "Endocrinology","Emergency Medicine","Family Medicine","Psychiatry"]
FACILITY_TYPES = ["Hospital","Clinic","Urgent Care","Specialty Center","Rehabilitation Center"]

ICD10_CODES = [
    ("I10",   "Essential hypertension",                  "Circulatory"),
    ("E11.9", "Type 2 diabetes mellitus without compl.", "Endocrine"),
    ("J06.9", "Acute upper respiratory infection",       "Respiratory"),
    ("M54.5", "Low back pain",                           "Musculoskeletal"),
    ("F32.9", "Major depressive disorder, single",       "Mental Health"),
    ("E78.5", "Hyperlipidemia, unspecified",             "Endocrine"),
    ("J18.9", "Pneumonia, unspecified",                  "Respiratory"),
    ("N39.0", "Urinary tract infection",                 "Genitourinary"),
    ("K21.0", "Gastro-oesophageal reflux with esophagitis","Digestive"),
    ("I25.10","Atherosclerotic heart disease, unspecified","Circulatory"),
    ("G43.909","Migraine, unspecified, not intractable", "Nervous System"),
    ("J45.909","Unspecified asthma, uncomplicated",      "Respiratory"),
    ("E11.65","Type 2 diabetes w/ hyperglycaemia",       "Endocrine"),
    ("M17.11","Primary osteoarthritis, right knee",      "Musculoskeletal"),
    ("F41.1", "Generalized anxiety disorder",            "Mental Health"),
    ("I48.91","Unspecified atrial fibrillation",         "Circulatory"),
    ("K57.30","Diverticulosis of large intestine",       "Digestive"),
    ("N18.3", "Chronic kidney disease, stage 3",         "Genitourinary"),
    ("C34.10","Malignant neoplasm of upper lobe bronchus","Neoplasms"),
    ("Z23",   "Encounter for immunization",              "Preventive"),
    ("Z00.00","Encounter for general adult exam",        "Preventive"),
    ("S72.001","Fracture of neck of femur",              "Injury"),
    ("I63.9", "Cerebral infarction, unspecified",        "Circulatory"),
    ("B34.9", "Viral infection, unspecified",            "Infectious"),
    ("L40.0", "Psoriasis vulgaris",                      "Skin"),
]

CPT_CODES = [
    ("99213","Office visit, established, low complexity",       "E&M",         85.00),
    ("99214","Office visit, established, moderate complexity",  "E&M",        145.00),
    ("99215","Office visit, established, high complexity",      "E&M",        210.00),
    ("99203","Office visit, new patient, low complexity",       "E&M",        115.00),
    ("99204","Office visit, new patient, moderate complexity",  "E&M",        180.00),
    ("99283","Emergency dept visit, moderate complexity",       "E&M",        320.00),
    ("99284","Emergency dept visit, high complexity",           "E&M",        450.00),
    ("80053","Comprehensive metabolic panel",                   "Laboratory",  40.00),
    ("85025","Complete blood count w/ differential",            "Laboratory",  30.00),
    ("84443","Thyroid stimulating hormone (TSH)",               "Laboratory",  55.00),
    ("83036","Hemoglobin A1c",                                  "Laboratory",  35.00),
    ("93000","Electrocardiogram (ECG)",                         "Diagnostic",  65.00),
    ("71046","Chest X-ray, 2 views",                           "Radiology",   95.00),
    ("72148","MRI lumbar spine w/o contrast",                   "Radiology",  780.00),
    ("27447","Total knee arthroplasty",                         "Surgery",  8500.00),
    ("43239","Upper GI endoscopy w/ biopsy",                    "Surgery",   950.00),
    ("45378","Colonoscopy, diagnostic",                         "Surgery",  1200.00),
    ("36415","Routine venipuncture",                            "Laboratory",  15.00),
    ("99406","Smoking cessation counseling, 3-10 min",          "Preventive",  30.00),
    ("90658","Influenza vaccine, 3+ yrs",                       "Preventive",  25.00),
]

MEDICATIONS = [
    ("Lisinopril",    "Lisinopril",      "ACE Inhibitor",     "Tablet","10 mg"),
    ("Metformin",     "Metformin HCl",   "Biguanide",         "Tablet","500 mg"),
    ("Atorvastatin",  "Atorvastatin",    "Statin",            "Tablet","40 mg"),
    ("Amlodipine",    "Amlodipine",      "Calcium Channel Blocker","Tablet","5 mg"),
    ("Omeprazole",    "Omeprazole",      "PPI",               "Capsule","20 mg"),
    ("Metoprolol",    "Metoprolol Succinate","Beta Blocker",  "Tablet","50 mg"),
    ("Levothyroxine", "Levothyroxine Na","Thyroid Hormone",   "Tablet","50 mcg"),
    ("Sertraline",    "Sertraline HCl",  "SSRI",              "Tablet","50 mg"),
    ("Gabapentin",    "Gabapentin",      "Anticonvulsant",    "Capsule","300 mg"),
    ("Hydrocodone",   "Hydrocodone/APAP","Opioid Analgesic",  "Tablet","5/325 mg"),
    ("Amoxicillin",   "Amoxicillin",     "Penicillin Antibiotic","Capsule","500 mg"),
    ("Albuterol",     "Albuterol Sulfate","Bronchodilator",   "Inhaler","90 mcg"),
    ("Losartan",      "Losartan Potassium","ARB",             "Tablet","50 mg"),
    ("Pantoprazole",  "Pantoprazole",    "PPI",               "Tablet","40 mg"),
    ("Prednisone",    "Prednisone",      "Corticosteroid",    "Tablet","10 mg"),
    ("Aspirin",       "Aspirin",         "NSAID/Antiplatelet","Tablet","81 mg"),
    ("Clopidogrel",   "Clopidogrel",     "Antiplatelet",      "Tablet","75 mg"),
    ("Warfarin",      "Warfarin Sodium", "Anticoagulant",     "Tablet","5 mg"),
    ("Furosemide",    "Furosemide",      "Loop Diuretic",     "Tablet","40 mg"),
    ("Duloxetine",    "Duloxetine HCl",  "SNRI",              "Capsule","60 mg"),
]

LAB_TESTS = [
    ("Glucose, Fasting",      "Chemistry",  "mg/dL",  70.0,  99.0),
    ("HbA1c",                 "Chemistry",  "%",       4.0,   5.6),
    ("Total Cholesterol",     "Lipid Panel","mg/dL",   0.0,  199.0),
    ("LDL Cholesterol",       "Lipid Panel","mg/dL",   0.0,  99.0),
    ("HDL Cholesterol",       "Lipid Panel","mg/dL",  40.0,  60.0),
    ("Triglycerides",         "Lipid Panel","mg/dL",   0.0, 149.0),
    ("Creatinine",            "Chemistry",  "mg/dL",  0.74,  1.35),
    ("eGFR",                  "Chemistry",  "mL/min",  60.0, 120.0),
    ("ALT",                   "Hepatic",    "U/L",      7.0,  56.0),
    ("AST",                   "Hepatic",    "U/L",     10.0,  40.0),
    ("TSH",                   "Thyroid",    "mIU/L",   0.4,   4.0),
    ("Hemoglobin",            "Hematology", "g/dL",   12.0,  17.5),
    ("WBC",                   "Hematology", "K/uL",    4.5,  11.0),
    ("Platelet Count",        "Hematology", "K/uL",  150.0, 400.0),
    ("Sodium",                "Electrolytes","mEq/L", 136.0, 145.0),
    ("Potassium",             "Electrolytes","mEq/L",   3.5,   5.0),
    ("BNP",                   "Cardiac",    "pg/mL",   0.0, 100.0),
    ("Troponin I",            "Cardiac",    "ng/mL",   0.0,   0.04),
    ("PSA",                   "Oncology",   "ng/mL",   0.0,   4.0),
    ("Urine Protein",         "Urinalysis", "mg/dL",   0.0,  14.0),
]

FREQUENCIES  = ["Once daily","Twice daily","Three times daily","Every 8 hours",
                 "Every 12 hours","As needed","Weekly","Every other day"]
ENCOUNTER_TYPES = ["Outpatient","Inpatient","Emergency","Telehealth","Follow-up","Preventive"]
CLAIM_STATUSES  = ["Paid","Denied","Pending","Partial","Appealed"]


# ── Build DB ──────────────────────────────────────────────────────────────────

if DB_PATH.exists():
    DB_PATH.unlink()

conn = sqlite3.connect(str(DB_PATH))
cur  = conn.cursor()

cur.executescript("""
PRAGMA foreign_keys = ON;

CREATE TABLE Facility (
    FacilityId   INTEGER PRIMARY KEY,
    Name         TEXT NOT NULL,
    Type         TEXT,
    Address      TEXT,
    City         TEXT,
    State        TEXT,
    ZipCode      TEXT,
    Phone        TEXT,
    BedCount     INTEGER
);

CREATE TABLE Provider (
    ProviderId   INTEGER PRIMARY KEY,
    FirstName    TEXT NOT NULL,
    LastName     TEXT NOT NULL,
    Specialty    TEXT,
    NPI          TEXT UNIQUE,
    Phone        TEXT,
    Email        TEXT,
    FacilityId   INTEGER REFERENCES Facility(FacilityId)
);

CREATE TABLE Payer (
    PayerId      INTEGER PRIMARY KEY,
    Name         TEXT NOT NULL,
    Type         TEXT,
    ContactPhone TEXT
);

CREATE TABLE Patient (
    PatientId    INTEGER PRIMARY KEY,
    FirstName    TEXT NOT NULL,
    LastName     TEXT NOT NULL,
    DateOfBirth  TEXT,
    Gender       TEXT,
    BloodType    TEXT,
    Phone        TEXT,
    Email        TEXT,
    Address      TEXT,
    City         TEXT,
    State        TEXT,
    ZipCode      TEXT
);

CREATE TABLE Insurance (
    InsuranceId  INTEGER PRIMARY KEY,
    PatientId    INTEGER REFERENCES Patient(PatientId),
    PayerId      INTEGER REFERENCES Payer(PayerId),
    PlanName     TEXT,
    MemberNumber TEXT,
    GroupNumber  TEXT,
    StartDate    TEXT,
    EndDate      TEXT
);

CREATE TABLE Diagnosis (
    DiagnosisId  INTEGER PRIMARY KEY,
    ICD10Code    TEXT NOT NULL UNIQUE,
    Description  TEXT,
    Category     TEXT
);

CREATE TABLE Procedure (
    ProcedureId  INTEGER PRIMARY KEY,
    CPTCode      TEXT NOT NULL UNIQUE,
    Description  TEXT,
    Category     TEXT,
    UnitCost     REAL
);

CREATE TABLE Medication (
    MedicationId INTEGER PRIMARY KEY,
    BrandName    TEXT,
    GenericName  TEXT,
    DrugClass    TEXT,
    Form         TEXT,
    Strength     TEXT
);

CREATE TABLE LabTest (
    LabTestId       INTEGER PRIMARY KEY,
    TestName        TEXT NOT NULL,
    Category        TEXT,
    Units           TEXT,
    NormalRangeLow  REAL,
    NormalRangeHigh REAL
);

CREATE TABLE Encounter (
    EncounterId   INTEGER PRIMARY KEY,
    PatientId     INTEGER REFERENCES Patient(PatientId),
    ProviderId    INTEGER REFERENCES Provider(ProviderId),
    FacilityId    INTEGER REFERENCES Facility(FacilityId),
    EncounterType TEXT,
    AdmitDate     TEXT,
    DischargeDate TEXT,
    ChiefComplaint TEXT,
    Status        TEXT DEFAULT 'Completed'
);

CREATE TABLE EncounterDiagnosis (
    EncounterDiagnosisId INTEGER PRIMARY KEY,
    EncounterId          INTEGER REFERENCES Encounter(EncounterId),
    DiagnosisId          INTEGER REFERENCES Diagnosis(DiagnosisId),
    IsPrimary            INTEGER DEFAULT 0
);

CREATE TABLE EncounterProcedure (
    EncounterProcedureId INTEGER PRIMARY KEY,
    EncounterId          INTEGER REFERENCES Encounter(EncounterId),
    ProcedureId          INTEGER REFERENCES Procedure(ProcedureId),
    Quantity             INTEGER DEFAULT 1,
    TotalCost            REAL
);

CREATE TABLE Claim (
    ClaimId      INTEGER PRIMARY KEY,
    EncounterId  INTEGER REFERENCES Encounter(EncounterId),
    PayerId      INTEGER REFERENCES Payer(PayerId),
    ClaimDate    TEXT,
    TotalAmount  REAL,
    PaidAmount   REAL,
    Status       TEXT
);

CREATE TABLE Prescription (
    PrescriptionId INTEGER PRIMARY KEY,
    EncounterId    INTEGER REFERENCES Encounter(EncounterId),
    PatientId      INTEGER REFERENCES Patient(PatientId),
    ProviderId     INTEGER REFERENCES Provider(ProviderId),
    MedicationId   INTEGER REFERENCES Medication(MedicationId),
    Dosage         TEXT,
    Frequency      TEXT,
    StartDate      TEXT,
    EndDate        TEXT,
    Refills        INTEGER DEFAULT 0
);

CREATE TABLE LabResult (
    LabResultId  INTEGER PRIMARY KEY,
    EncounterId  INTEGER REFERENCES Encounter(EncounterId),
    PatientId    INTEGER REFERENCES Patient(PatientId),
    LabTestId    INTEGER REFERENCES LabTest(LabTestId),
    ResultDate   TEXT,
    ResultValue  REAL,
    IsAbnormal   INTEGER DEFAULT 0
);
""")

# ── Facilities ────────────────────────────────────────────────────────────────
facility_names = [
    ("Riverside General Hospital","Hospital"),("Metro Cardiology Center","Specialty Center"),
    ("Sunrise Urgent Care","Urgent Care"),("Oakwood Medical Clinic","Clinic"),
    ("St. Mary's Medical Center","Hospital"),("Valley Rehabilitation Center","Rehabilitation Center"),
    ("Lakeview Pediatric Clinic","Clinic"),("Summit Oncology Institute","Specialty Center"),
]
facilities = []
for i,(name,ftype) in enumerate(facility_names,1):
    city,state = random.choice(CITIES_STATES)
    beds = random.randint(50,600) if ftype=="Hospital" else None
    cur.execute("INSERT INTO Facility VALUES(?,?,?,?,?,?,?,?,?)",
                (i,name,ftype,f"{random.randint(100,9999)} Main St",city,state,
                 f"{random.randint(10000,99999)}",rand_phone(),beds))
    facilities.append(i)

# ── Providers ─────────────────────────────────────────────────────────────────
providers = []
for i in range(1,21):
    gender = random.choice(["M","F"])
    fn = random.choice(FIRST_NAMES_M if gender=="M" else FIRST_NAMES_F)
    ln = random.choice(LAST_NAMES)
    sp = random.choice(SPECIALTIES)
    fid = random.choice(facilities)
    cur.execute("INSERT INTO Provider VALUES(?,?,?,?,?,?,?,?)",
                (i,fn,ln,sp,rand_npi(),rand_phone(),
                 f"{fn.lower()}.{ln.lower()}@health.org",fid))
    providers.append(i)

# ── Payers ────────────────────────────────────────────────────────────────────
payer_data = [
    ("BlueCross BlueShield","Commercial"),("Aetna","Commercial"),
    ("UnitedHealthcare","Commercial"),("Medicare","Government"),
    ("Medicaid","Government"),("Cigna","Commercial"),
]
payers = []
for i,(name,ptype) in enumerate(payer_data,1):
    cur.execute("INSERT INTO Payer VALUES(?,?,?,?)",(i,name,ptype,rand_phone()))
    payers.append(i)

# ── Patients ──────────────────────────────────────────────────────────────────
patients = []
for i in range(1,101):
    gender = random.choice(["Male","Female"])
    fn = random.choice(FIRST_NAMES_M if gender=="Male" else FIRST_NAMES_F)
    ln = random.choice(LAST_NAMES)
    dob = rand_date(date(1940,1,1), date(2005,12,31))
    city,state = random.choice(CITIES_STATES)
    cur.execute("INSERT INTO Patient VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (i,fn,ln,dob,gender,random.choice(BLOOD_TYPES),rand_phone(),
                 f"{fn.lower()}.{ln.lower()}{i}@email.com",
                 f"{random.randint(100,9999)} Oak Ave",city,state,
                 f"{random.randint(10000,99999)}"))
    patients.append(i)

# ── Insurance ─────────────────────────────────────────────────────────────────
for i,pid in enumerate(patients,1):
    payer = random.choice(payers)
    start = rand_date(date(2020,1,1), date(2023,1,1))
    end   = rand_date(date(2024,1,1), date(2026,12,31))
    plans = ["Gold HMO","Silver PPO","Bronze EPO","Platinum POS","Medicare Advantage"]
    cur.execute("INSERT INTO Insurance VALUES(?,?,?,?,?,?,?,?)",
                (i,pid,payer,random.choice(plans),
                 f"MBR{random.randint(100000,999999)}",
                 f"GRP{random.randint(1000,9999)}",start,end))

# ── Reference tables ──────────────────────────────────────────────────────────
diagnoses = []
for i,(code,desc,cat) in enumerate(ICD10_CODES,1):
    cur.execute("INSERT INTO Diagnosis VALUES(?,?,?,?)",(i,code,desc,cat))
    diagnoses.append(i)

procedures = []
for i,(cpt,desc,cat,cost) in enumerate(CPT_CODES,1):
    cur.execute("INSERT INTO Procedure VALUES(?,?,?,?,?)",(i,cpt,desc,cat,cost))
    procedures.append(i)

medications = []
for i,(brand,generic,cls,form,strength) in enumerate(MEDICATIONS,1):
    cur.execute("INSERT INTO Medication VALUES(?,?,?,?,?,?)",
                (i,brand,generic,cls,form,strength))
    medications.append(i)

lab_tests = []
for i,(name,cat,units,lo,hi) in enumerate(LAB_TESTS,1):
    cur.execute("INSERT INTO LabTest VALUES(?,?,?,?,?,?)",(i,name,cat,units,lo,hi))
    lab_tests.append((i,lo,hi))

# ── Encounters ────────────────────────────────────────────────────────────────
complaints = [
    "Chest pain","Shortness of breath","Abdominal pain","Headache","Dizziness",
    "Fatigue","Fever","Back pain","Joint pain","Follow-up diabetes management",
    "Annual wellness exam","Hypertension management","Medication refill","Cough",
    "Skin rash","Urinary symptoms","Depression screening","Weight management",
]

encounters = []
ep_rows, ed_rows, rx_rows, lr_rows, claim_rows = [], [], [], [], []
ep_id = ed_id = rx_id = lr_id = cl_id = 1

for enc_id in range(1, 301):
    pid  = random.choice(patients)
    prov = random.choice(providers)
    fac  = random.choice(facilities)
    etype = random.choice(ENCOUNTER_TYPES)
    admit = rand_date(date(2021,1,1), date(2024,12,31))
    if etype == "Inpatient":
        discharge = (date.fromisoformat(admit) + timedelta(days=random.randint(1,10))).isoformat()
    else:
        discharge = admit
    complaint = random.choice(complaints)

    cur.execute("INSERT INTO Encounter VALUES(?,?,?,?,?,?,?,?,?)",
                (enc_id,pid,prov,fac,etype,admit,discharge,complaint,"Completed"))
    encounters.append(enc_id)

    # ── Diagnoses per encounter (1–3) ─────────────────────────────────────────
    for j, did in enumerate(random.sample(diagnoses, k=random.randint(1,3))):
        cur.execute("INSERT INTO EncounterDiagnosis VALUES(?,?,?,?)",
                    (ed_id, enc_id, did, 1 if j==0 else 0))
        ed_id += 1

    # ── Procedures per encounter (1–2) ────────────────────────────────────────
    for proc_id in random.sample(procedures, k=random.randint(1,2)):
        cur.execute(
            "SELECT UnitCost FROM Procedure WHERE ProcedureId=?", (proc_id,)
        )
        unit_cost = cur.fetchone()[0]
        qty = random.randint(1, 2)
        cur.execute("INSERT INTO EncounterProcedure VALUES(?,?,?,?,?)",
                    (ep_id, enc_id, proc_id, qty, round(unit_cost * qty, 2)))
        ep_id += 1

    # ── Claims ────────────────────────────────────────────────────────────────
    total = round(random.uniform(80, 4000), 2)
    paid  = round(total * random.uniform(0.0, 1.0), 2)
    status = random.choice(CLAIM_STATUSES)
    claim_date = (date.fromisoformat(discharge) + timedelta(days=random.randint(1,30))).isoformat()
    cur.execute("INSERT INTO Claim VALUES(?,?,?,?,?,?,?)",
                (cl_id, enc_id, random.choice(payers), claim_date, total, paid, status))
    cl_id += 1

    # ── Prescriptions (60 % of encounters) ───────────────────────────────────
    if random.random() < 0.60:
        for med_id in random.sample(medications, k=random.randint(1,2)):
            start = admit
            end_rx = (date.fromisoformat(admit) + timedelta(days=random.choice([30,60,90]))).isoformat()
            cur.execute("INSERT INTO Prescription VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (rx_id, enc_id, pid, prov, med_id,
                         "As prescribed", random.choice(FREQUENCIES),
                         start, end_rx, random.randint(0, 5)))
            rx_id += 1

    # ── Lab results (50 % of encounters, 1–4 tests) ───────────────────────────
    if random.random() < 0.50:
        for (tid, lo, hi) in random.sample(lab_tests, k=random.randint(1,4)):
            abnormal = random.random() < 0.25
            if abnormal:
                val = round(random.uniform(hi * 1.05, hi * 1.5), 2) if random.random() < 0.5 \
                      else round(random.uniform(lo * 0.5, lo * 0.95), 2) if lo > 0 else round(hi * 1.2, 2)
            else:
                val = round(random.uniform(lo if lo > 0 else 0, hi), 2)
            cur.execute("INSERT INTO LabResult VALUES(?,?,?,?,?,?,?)",
                        (lr_id, enc_id, pid, tid, admit, val, int(abnormal)))
            lr_id += 1

conn.commit()
conn.close()

print(f"✓  healthcare.db created at {DB_PATH}")
print(f"   Facilities : 8    Providers  : 20    Payers  : {len(payer_data)}")
print(f"   Patients   : 100  Encounters : 300   Claims  : {cl_id-1}")
print(f"   Diagnoses  : {len(ICD10_CODES)}   Procedures : {len(CPT_CODES)}    Medications : {len(MEDICATIONS)}")
print(f"   LabTests   : {len(LAB_TESTS)}    LabResults : {lr_id-1}  Prescriptions: {rx_id-1}")
