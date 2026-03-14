from models import db, Lead

CURSOS = {
    'PREPATOP': ['Oposiciones AGE A1', 'Oposiciones AGE A2', 'Oposiciones Hacienda', 'Oposiciones Justicia'],
    'PREPARASECUNDARIA': ['Matematicas Secundaria', 'Lengua Secundaria', 'Ingles Secundaria', 'Biologia Secundaria'],
    'PREPARAANDALUCIA': ['Administrativo Junta', 'Auxiliar Junta', 'Gestion Procesal', 'Tramitacion Procesal'],
}

ESPECIALIDADES = {
    'PREPATOP': ['Infantil', 'Primaria', 'Ingles', 'PT', 'PT Online', 'EF', 'AL'],
    'PREPARAANDALUCIA': ['EF', 'AL', 'PT', 'Primaria'],
    'PREPARASECUNDARIA': ['Tecnologia', 'Historia', 'Lengua', 'Economia', 'Latin', 'FyQ', 'Filosofia', 'Ingles'],
}


def seed_database():
    """No seed data - user will add real data."""
    pass
