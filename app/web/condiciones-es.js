/* Nombres de patologías en castellano.

   Las fuentes son todas en inglés: MED-RT usa descriptores MeSH y el catálogo
   CIE-10 es el de CMS. Un médico uruguayo no busca "Liver Diseases" ni lee
   "Thrombocytopenia" en una alerta.

   Se traduce a mano lo que efectivamente se muestra o se busca, ordenado por
   cuántas alertas dispara. Lo que no está traducido se muestra tal cual: una
   traducción automática en contexto clínico es peor que el inglés, porque el
   inglés se nota y la traducción inventada no.

   `CONDICION_ES` se usa para MOSTRAR (nombres MeSH, que es lo que viene en las
   alertas) y también como SINÓNIMO DE BÚSQUEDA para los códigos CIE-10, así
   quien escribe "hepática" encuentra "Liver disease". */

const CONDICION_ES = {
  /* --- estados fisiológicos --- */
  "Pregnancy": "Embarazo",
  "Pregnancy Trimester, First": "Embarazo — primer trimestre",
  "Pregnancy Trimester, Second": "Embarazo — segundo trimestre",
  "Pregnancy Trimester, Third": "Embarazo — tercer trimestre",
  "Lactation": "Lactancia",
  "Breast Feeding": "Lactancia",
  "Infant": "Lactante",
  "Infant, Newborn": "Recién nacido",
  "Child": "Niño",
  "Aged": "Adulto mayor",

  /* --- riñón --- */
  "Renal Insufficiency": "Insuficiencia renal",
  "Renal Insufficiency, Chronic": "Insuficiencia renal crónica",
  // CIE-10 (CMS): los anclajes de N18 que ofrece el autocompletado, y el
  // título de N18.5, que usa el ejemplo con paciente.
  "Chronic kidney disease (CKD)": "Enfermedad renal crónica (ERC)",
  "Chronic kidney disease, unspecified": "Enfermedad renal crónica, no especificada",
  "Chronic kidney disease, stage 5": "Enfermedad renal crónica, estadio 5",
  "Kidney Diseases": "Enfermedad renal",
  "Kidney Failure, Chronic": "Insuficiencia renal crónica terminal",
  "Acute Kidney Injury": "Insuficiencia renal aguda",
  "Anuria": "Anuria",
  "Nephrotic Syndrome": "Síndrome nefrótico",
  "Glomerulonephritis": "Glomerulonefritis",

  /* --- hígado --- */
  "Liver Diseases": "Enfermedad hepática",
  "Liver Failure": "Insuficiencia hepática",
  "Hepatic Insufficiency": "Insuficiencia hepática",
  "Liver Cirrhosis": "Cirrosis hepática",
  "Hepatitis": "Hepatitis",
  "Liver Failure, Acute": "Insuficiencia hepática aguda",
  "Jaundice": "Ictericia",

  /* --- corazón y circulación --- */
  "Heart Failure": "Insuficiencia cardíaca",
  "Hypertension": "Hipertensión arterial",
  "Hypotension": "Hipotensión",
  "Myocardial Infarction": "Infarto de miocardio",
  "Coronary Disease": "Enfermedad coronaria",
  "Arrhythmias, Cardiac": "Arritmia cardíaca",
  "Bradycardia": "Bradicardia",
  "Tachycardia": "Taquicardia",
  "Heart Block": "Bloqueo cardíaco",
  "Atrioventricular Block": "Bloqueo auriculoventricular",
  "Sick Sinus Syndrome": "Enfermedad del nódulo sinusal",
  "Shock, Cardiogenic": "Shock cardiogénico",
  "Long QT Syndrome": "Síndrome de QT largo",
  "Angina Pectoris": "Angina de pecho",
  "Cardiomyopathies": "Miocardiopatía",
  "Aortic Valve Stenosis": "Estenosis aórtica",
  "Thromboembolism": "Tromboembolismo",
  "Thrombophlebitis": "Tromboflebitis",
  "Venous Thrombosis": "Trombosis venosa",
  "Stroke": "Accidente cerebrovascular",
  "Cerebral Infarction": "Infarto cerebral",

  /* --- sangre --- */
  "Thrombocytopenia": "Plaquetopenia",
  "Neutropenia": "Neutropenia",
  "Anemia": "Anemia",
  "Anemia, Aplastic": "Anemia aplásica",
  "Agranulocytosis": "Agranulocitosis",
  "Hemorrhage": "Hemorragia",
  "Hemorrhagic Disorders": "Trastorno hemorrágico",
  "Blood Coagulation Disorders": "Trastorno de la coagulación",
  "Bone Marrow Diseases": "Enfermedad de la médula ósea",
  "Porphyrias": "Porfiria",
  "Glucosephosphate Dehydrogenase Deficiency": "Déficit de G6PD",

  /* --- respiratorio --- */
  "Asthma": "Asma",
  "Status Asthmaticus": "Estado asmático",
  "Pulmonary Edema": "Edema pulmonar",
  "Respiratory Insufficiency": "Insuficiencia respiratoria",
  "Pulmonary Disease, Chronic Obstructive": "EPOC",
  "Respiratory Depression": "Depresión respiratoria",
  "Sleep Apnea Syndromes": "Apnea del sueño",

  /* --- digestivo --- */
  "Intestinal Obstruction": "Obstrucción intestinal",
  "Peptic Ulcer": "Úlcera péptica",
  "Gastrointestinal Hemorrhage": "Hemorragia digestiva",
  "Pancreatitis": "Pancreatitis",
  "Inflammatory Bowel Diseases": "Enfermedad inflamatoria intestinal",
  "Colitis, Ulcerative": "Colitis ulcerosa",
  "Diarrhea": "Diarrea",
  "Constipation": "Estreñimiento",
  "Ileus": "Íleo",

  /* --- metabolismo y endocrino --- */
  "Diabetes Mellitus": "Diabetes mellitus",
  "Diabetes Mellitus, Type 1": "Diabetes tipo 1",
  "Diabetes Mellitus, Type 2": "Diabetes tipo 2",
  "Hyperkalemia": "Hiperpotasemia",
  "Hypokalemia": "Hipopotasemia",
  "Hypercalcemia": "Hipercalcemia",
  "Hyponatremia": "Hiponatremia",
  "Hyperthyroidism": "Hipertiroidismo",
  "Hypothyroidism": "Hipotiroidismo",
  "Pheochromocytoma": "Feocromocitoma",
  "Dehydration": "Deshidratación",
  "Obesity": "Obesidad",
  "Gout": "Gota",
  "Acidosis": "Acidosis",

  /* --- neurológico y psiquiátrico --- */
  "Epilepsy": "Epilepsia",
  "Seizures": "Convulsiones",
  "Myasthenia Gravis": "Miastenia gravis",
  "Parkinson Disease": "Enfermedad de Parkinson",
  "Dementia": "Demencia",
  "Depression": "Depresión",
  "Depressive Disorder": "Trastorno depresivo",
  "Bipolar Disorder": "Trastorno bipolar",
  "Psychotic Disorders": "Trastorno psicótico",
  "Schizophrenia": "Esquizofrenia",
  "Coma": "Coma",
  "Confusion": "Confusión",
  "Suicide": "Riesgo de suicidio",
  "Substance-Related Disorders": "Trastorno por consumo de sustancias",
  "Alcoholism": "Alcoholismo",

  /* --- otros --- */
  "Hypersensitivity": "Hipersensibilidad",
  "Drug Hypersensitivity": "Alergia a medicamentos",
  "Glaucoma": "Glaucoma",
  "Glaucoma, Angle-Closure": "Glaucoma de ángulo cerrado",
  "Breast Neoplasms": "Cáncer de mama",
  "Neoplasms, Hormone-Dependent": "Tumor hormonodependiente",
  "Prostatic Hyperplasia": "Hiperplasia prostática",
  "Urinary Retention": "Retención urinaria",
  "Osteoporosis": "Osteoporosis",
  "Infections": "Infección",
  "Lupus Erythematosus, Systemic": "Lupus eritematoso sistémico",
  "Wounds and Injuries": "Traumatismo",
};

/* Sinónimos en castellano para BUSCAR sobre los nombres CIE-10, que están en
   inglés. Sin esto, escribir "hepática" no devuelve nada aunque el catálogo
   tenga 130 alertas colgadas de "Diseases of liver".
   La búsqueda expande el término y consulta también por su equivalente. */
const BUSQUEDA_ES_EN = {
  "higado": "liver", "hepatic": "hepatic", "hepatica": "liver",
  "hepatico": "liver", "cirrosis": "cirrhosis", "hepatitis": "hepatitis",
  "rinon": "kidney", "renal": "renal", "insuficiencia renal": "renal failure",
  "corazon": "heart", "cardiaco": "cardiac", "cardiaca": "cardiac",
  "insuficiencia cardiaca": "heart failure", "infarto": "infarction",
  "arritmia": "arrhythmia", "bradicardia": "bradycardia",
  "taquicardia": "tachycardia", "bloqueo": "block",
  "hipertension": "hypertension", "hipotension": "hypotension",
  "embarazo": "pregnan", "lactancia": "lactation",
  "asma": "asthma", "pulmonar": "pulmonary", "pulmon": "lung",
  "respiratoria": "respiratory", "respiratorio": "respiratory",
  "epilepsia": "epilepsy", "convulsiones": "seizure",
  "diabetes": "diabetes", "tiroides": "thyroid",
  "anemia": "anemia", "hemorragia": "hemorrhage",
  "plaquetopenia": "thrombocytopenia", "trombocitopenia": "thrombocytopenia",
  "neutropenia": "neutropenia", "coagulacion": "coagulation",
  "ulcera": "ulcer", "gastrica": "gastric", "intestinal": "intestinal",
  "obstruccion": "obstruction", "pancreatitis": "pancreatitis",
  "glaucoma": "glaucoma", "prostata": "prostat", "prostatica": "prostat",
  "depresion": "depress", "psicosis": "psychotic",
  "demencia": "dementia", "parkinson": "parkinson",
  "miastenia": "myasthenia", "porfiria": "porphyria",
  "cancer": "malignant", "tumor": "neoplasm", "mama": "breast",
  "alergia": "allergy", "hipersensibilidad": "hypersensitivity",
  "shock": "shock", "coma": "coma", "gota": "gout",
  "obesidad": "obesity", "osteoporosis": "osteoporosis",
  "lupus": "lupus", "deshidratacion": "dehydration",
  "potasio": "potassium", "sodio": "sodium", "calcio": "calcium",
};

const condEs = (n) => CONDICION_ES[n] || n;
