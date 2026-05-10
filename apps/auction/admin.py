# apps/auction/admin.py
from django.contrib import admin
from .models import AuctionParticipant, Bid, AuctionWin


@admin.register(AuctionParticipant)
class AuctionParticipantAdmin(admin.ModelAdmin):
    list_display = ('auction', 'user', 'joined_at', 'entry_fee_paid')
    list_filter = ('auction', 'entry_fee_paid', 'joined_at')
    search_fields = ('user__email', 'auction__product_name')
    readonly_fields = ('joined_at',)
    actions = ['delete_selected_participants']

    def delete_selected_participants(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} participant(s) deleted successfully.")
    delete_selected_participants.short_description = "Delete selected participants"


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('auction', 'user', 'bid_number', 'bid_at', 'coins_deducted')
    list_filter = ('auction', 'bid_at')
    search_fields = ('user__email', 'auction__product_name', 'bid_number')
    readonly_fields = ('bid_at', 'coins_deducted')
    ordering = ('-bid_at',)
    actions = ['delete_selected_bids']

    def delete_selected_bids(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} bid(s) deleted successfully.")
    delete_selected_bids.short_description = "Delete selected bids"


@admin.register(AuctionWin)
class AuctionWinAdmin(admin.ModelAdmin):
    list_display = ('auction', 'winner', 'won_at', 'final_bid_amount', 'claimed', 'claimed_at')
    list_filter = ('claimed', 'won_at', 'auction__status')
    search_fields = ('winner__email', 'auction__product_name')
    readonly_fields = ('won_at', 'final_bid_amount')
    actions = ['delete_selected_wins']

    def delete_selected_wins(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} win record(s) deleted successfully.")
    delete_selected_wins.short_description = "Delete selected win records"