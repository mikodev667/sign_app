from admissions.models import AdmissionCommissionProfile, AdmissionViceRectorProfile


def admissions_access(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {
            "has_admission_vice_rector_profile": False,
            "has_admission_commission_profile": False,
        }

    return {
        "has_admission_vice_rector_profile": AdmissionViceRectorProfile.objects.filter(
            user=user,
            is_active=True,
        ).exists(),
        "has_admission_commission_profile": AdmissionCommissionProfile.objects.filter(
            user=user,
            is_active=True,
        ).exists(),
    }
