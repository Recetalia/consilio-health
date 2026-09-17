"""El perfil del paciente y su traducción a condiciones."""

import pytest

from app.services.patient_profile import PatientProfile


class TestEmbarazo:
    def test_sin_semanas_activa_todos_los_trimestres(self):
        codes = PatientProfile(embarazo=True).mesh_codes()
        assert "D011247" in codes                       # Pregnancy
        assert {"D011261", "D011262", "D011263"} <= codes

    @pytest.mark.parametrize("semana,trimestre", [(8, "D011261"), (20, "D011262"), (35, "D011263")])
    def test_con_semanas_acota_al_trimestre(self, semana, trimestre):
        codes = PatientProfile(embarazo=True, semanas_gestacion=semana).mesh_codes()
        assert trimestre in codes
        otros = {"D011261", "D011262", "D011263"} - {trimestre}
        assert not (otros & codes), "no debería activar los otros trimestres"

    def test_el_generico_se_activa_siempre(self):
        # La mayoría de las contraindicaciones de MED-RT cuelgan de "Pregnancy"
        # a secas: perderlas por acotar al trimestre sería el peor intercambio.
        assert "D011247" in PatientProfile(embarazo=True, semanas_gestacion=20).mesh_codes()


class TestAlergia:
    def test_no_activa_ninguna_condicion(self):
        """Regresión del falso positivo más grave que tuvo este módulo.

        Con la alergia como flag mapeado a Drug Hypersensitivity, declarar
        alergia a la aspirina marcaba como contraindicados los 1.338 fármacos
        que tienen ese descriptor — incluida la metformina. La alergia se
        resuelve por fármaco, no por condición.
        """
        assert PatientProfile(alergias=["aspirina", "penicilina"]).mesh_codes() == set()


class TestFuncionOrganica:
    @pytest.mark.parametrize("valor", ["moderada", "grave", "leve"])
    def test_alterada_activa(self, valor):
        assert "D051437" in PatientProfile(funcion_renal=valor).mesh_codes()

    @pytest.mark.parametrize("valor", [None, "", "ninguna", "normal", "Normal"])
    def test_normal_no_activa(self, valor):
        assert PatientProfile(funcion_renal=valor).mesh_codes() == set()


class TestAvisosDePerfil:
    def test_embarazo_con_sexo_masculino(self):
        assert PatientProfile(sexo="M", embarazo=True).warnings()

    def test_semanas_sin_embarazo(self):
        assert PatientProfile(semanas_gestacion=20).warnings()

    def test_perfil_coherente_no_avisa(self):
        assert PatientProfile(sexo="F", embarazo=True, semanas_gestacion=20).warnings() == []

    def test_perfil_vacio_no_activa_nada(self):
        p = PatientProfile()
        assert p.mesh_codes() == set() and not p.has_data()
