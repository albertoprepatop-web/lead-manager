from models import db, Lead

CURSOS = {
    'PREPATOP': ['Oposiciones AGE A1', 'Oposiciones AGE A2', 'Oposiciones Hacienda', 'Oposiciones Justicia'],
    'PREPARASECUNDARIA': ['Matematicas Secundaria', 'Lengua Secundaria', 'Ingles Secundaria', 'Biologia Secundaria'],
    'PREPARAANDALUCIA': ['Administrativo Junta', 'Auxiliar Junta', 'Gestion Procesal', 'Tramitacion Procesal'],
}


def seed_database():
    """No seed data - user will add real data."""
    pass
