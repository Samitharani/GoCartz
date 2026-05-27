from django.contrib import admin
from .models import *


class UserProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'role',
        'is_vendor',
        'is_vendor_approved',
        'vendor_name',
        'business_category',
    ]
    list_filter = ['role', 'is_vendor_approved', 'is_vendor']
    search_fields = ['user__username', 'vendor_name', 'business_category']
    actions = ['approve_sellers']

    def approve_sellers(self, request, queryset):
        updated = queryset.update(is_vendor_approved=True)
        self.message_user(request, f"{updated} seller account(s) approved.")
    approve_sellers.short_description = 'Approve selected seller accounts'


admin.site.register(Category)
admin.site.register(CommissionSetting)
admin.site.register(Product)
admin.site.register(Review)
admin.site.register(Favourite)
admin.site.register(Address)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(UserProfile, UserProfileAdmin)
