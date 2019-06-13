from vivarium_public_health.metrics import Disability


class DisabilityObserver(Disability):
    """Standard vph disability observer only includes DiseaseModel and
    RiskAttributableDisease models. We need to extend it to include our
    custom iron deficiency hemoglobin component."""
    def setup(self, builder):
        super().setup(builder)
        self.causes.append('iron_deficiency')
        self.disability_weight_pipelines['iron_deficiency'] = builder.value.get_value('iron_deficiency.disability_weight')
