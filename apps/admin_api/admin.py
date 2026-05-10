# apps/admin_api/admin.py
from django.contrib import admin
from .models import Category, Auction, CoinPackage, AuctionStatus


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    actions = ['delete_selected_categories']

    def delete_selected_categories(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} category/categories deleted successfully.")
    delete_selected_categories.short_description = "Delete selected categories"


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = (
        'auction_id', 'product_name', 'category', 'status',
        'auction_price', 'market_price', 'entry_fee_coins',
        'created_at', 'scheduled_time', 'end_time'
    )
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('product_name', 'description', 'category__name')
    readonly_fields = ('created_by', 'created_at', 'current_bid', 'last_bid_time')
    date_hierarchy = 'created_at'
    actions = ['delete_selected_auctions', 'mark_as_ended', 'mark_as_published']

    fieldsets = (
        ('Basic Info', {
            'fields': ('product_name', 'category', 'description', 'product_image')
        }),
        ('Pricing', {
            'fields': ('market_price', 'auction_price', 'entry_fee_coins')
        }),
        ('Timing', {
            'fields': ('status', 'scheduled_time', 'auction_duration', 'winning_claim_window', 'end_time')
        }),
        ('Meta', {
            'fields': ('created_by', 'created_at', 'current_bid', 'last_bid_time'),
            'classes': ('collapse',)
        }),
    )

    def auction_id(self, obj):
        return obj.id
    auction_id.short_description = 'ID'

    def delete_selected_auctions(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} auction(s) deleted successfully.")
    delete_selected_auctions.short_description = "Delete selected auctions"

    def mark_as_ended(self, request, queryset):
        updated = queryset.filter(status=AuctionStatus.PUBLISH).update(status=AuctionStatus.ENDED)
        self.message_user(request, f"{updated} auction(s) marked as ended.")
    mark_as_ended.short_description = "Mark selected as Ended"

    def mark_as_published(self, request, queryset):
        updated = queryset.filter(status=AuctionStatus.SCHEDULE).update(status=AuctionStatus.PUBLISH)
        self.message_user(request, f"{updated} auction(s) marked as Published.")
    mark_as_published.short_description = "Mark selected as Published"


@admin.register(CoinPackage)
class CoinPackageAdmin(admin.ModelAdmin):
    list_display = ('coins', 'price_sar', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('coins', 'price_sar')
    actions = ['delete_selected_packages', 'activate_packages', 'deactivate_packages']

    def delete_selected_packages(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} package(s) deleted successfully.")
    delete_selected_packages.short_description = "Delete selected packages"

    def activate_packages(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} package(s) activated.")
    activate_packages.short_description = "Activate selected packages"

    def deactivate_packages(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} package(s) deactivated.")
    deactivate_packages.short_description = "Deactivate selected packages"