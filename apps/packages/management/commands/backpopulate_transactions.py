from django.core.management.base import BaseCommand
from django.db import transaction
from apps.auction.models import Bid, AuctionParticipant
from apps.packages.models import CoinTransaction

class Command(BaseCommand):
    help = 'Backpopulate CoinTransaction history from existing Bids and AuctionParticipants'

    def handle(self, *args, **options):
        self.stdout.write("Starting transaction backpopulation...")

        # 1. Backpopulate Bids
        bids = Bid.objects.all()
        bid_count = 0
        for bid in bids:
            # Check if transaction already exists for this bid
            if not CoinTransaction.objects.filter(reference_type='bid', reference_id=bid.id).exists():
                with transaction.atomic():
                    # Create transaction and manually set created_at
                    tx = CoinTransaction(
                        user=bid.user,
                        transaction_type='bid',
                        amount=bid.coins_deducted,
                        description=f"Bid #{bid.bid_number} on Auction #{bid.auction.id} ({bid.auction.product_name})",
                        reference_id=bid.id,
                        reference_type='bid'
                    )
                    tx.save()
                    # Override auto_now_add for historical accuracy
                    CoinTransaction.objects.filter(id=tx.id).update(created_at=bid.bid_at)
                    bid_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully created {bid_count} transaction records for bids."))

        # 2. Backpopulate Entry Fees
        participants = AuctionParticipant.objects.filter(entry_fee_paid=True)
        fee_count = 0
        for p in participants:
            # Check if transaction already exists for this participant
            if not CoinTransaction.objects.filter(reference_type='participant', reference_id=p.id).exists():
                with transaction.atomic():
                    tx = CoinTransaction(
                        user=p.user,
                        transaction_type='entry_fee',
                        amount=p.auction.entry_fee_coins,
                        description=f"Entry fee for Auction #{p.auction.id} ({p.auction.product_name})",
                        reference_id=p.id,
                        reference_type='participant'
                    )
                    tx.save()
                    # Override auto_now_add
                    CoinTransaction.objects.filter(id=tx.id).update(created_at=p.joined_at)
                    fee_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully created {fee_count} transaction records for entry fees."))
        self.stdout.write("Backpopulation completed.")
