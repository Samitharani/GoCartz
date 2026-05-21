from django import forms
from .models import UserProfile

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['phone', 'gender', 'dob', 'profile_picture']
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'})
        }
