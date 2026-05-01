from django.db import migrations


GRADE_SCALES = {
    "/20": [
        ("16.00", "20.00", "Très Bien", "20.00"),
        ("14.00", "15.99", "Bien", "15.99"),
        ("12.00", "13.99", "Assez Bien", "13.99"),
        ("10.00", "11.99", "Passable", "11.99"),
        ("0.00", "9.99", "Insuffisant", "9.99"),
    ],
    "/10": [
        ("8.00", "10.00", "Très Bien", "10.00"),
        ("7.00", "7.99", "Bien", "7.99"),
        ("6.00", "6.99", "Assez Bien", "6.99"),
        ("5.00", "5.99", "Passable", "5.99"),
        ("0.00", "4.99", "Insuffisant", "4.99"),
    ],
}


def seed_grade_scales(apps, schema_editor):
    GradeScale = apps.get_model("examination", "GradeScale")
    GradeScaleRule = apps.get_model("examination", "GradeScaleRule")

    for scale_name, rules in GRADE_SCALES.items():
        scale, _ = GradeScale.objects.get_or_create(name=scale_name)
        for min_grade, max_grade, letter, numeric in rules:
            GradeScaleRule.objects.get_or_create(
                grade_scale=scale,
                min_grade=min_grade,
                max_grade=max_grade,
                defaults={
                    "letter_grade": letter,
                    "numeric_scale": numeric,
                },
            )


def unseed_grade_scales(apps, schema_editor):
    GradeScale = apps.get_model("examination", "GradeScale")
    GradeScale.objects.filter(name__in=GRADE_SCALES.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("examination", "0002_result_average_result_mention_result_rank_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_grade_scales, unseed_grade_scales),
    ]
