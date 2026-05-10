import random
import string
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.packages.models import UserWallet, CoinTransaction
from apps.admin_api.models import Auction, Category
from apps.auction.models import Bid
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Verify Coin History API'

    def handle(self, *args, **options):
        email = f"test_history_{''.join(random.choices(string.ascii_lowercase, k=5))}@example.com"
        user = User.objects.create_user(email=email, password="password123")
        UserWallet.objects.create(user=user, coins=100)

        client = APIClient()
        client.force_authenticate(user=user)

        self.stdout.write(f"Created test user: {email}")

        # 1. Mock a purchase
        CoinTransaction.objects.create(
            user=user,
            transaction_type='purchase',
            amount=50,
            description="Test Purchase"
        )
        self.stdout.write("Created test purchase transaction")

        # 2. Mock a bid expense
        cat, _ = Category.objects.get_or_create(name="Test Cat")
        auction = Auction.objects.create(
            product_name="Test Auction",
            category=cat,
            market_price=100,
            auction_price=1,
            entry_fee_coins=5,
            auction_duration=timedelta(minutes=5),
            winning_claim_window=timedelta(hours=1)
        )
        
        CoinTransaction.objects.create(
            user=user,
            transaction_type='entry_fee',
            amount=5,
            description=f"Entry fee for Auction #{auction.id}"
        )
        
        CoinTransaction.objects.create(
            user=user,
            transaction_type='bid',
            amount=1,
            description=f"Bid on Auction #{auction.id}"
        )
        self.stdout.write("Created test expense transactions")

        # 3. Test Purchase History API
        response = client.get('/api/packages/purchase-history/')
        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Purchase History API success"))
            if len(response.data) > 0:
                 self.stdout.write(f"   Found {len(response.data)} purchase records")
            else:
                 self.stdout.write(self.style.ERROR("   No purchase records found!"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Purchase History API failed: {response.status_code}"))

        # 4. Test Expense History API
        response = client.get('/api/packages/expense-history/')
        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Expense History API success"))
            data = response.data
            if "transactions" in data and "total_in" in data and "total_out" in data:
                self.stdout.write(f"   Total In: {data['total_in']}, Total Out: {data['total_out']}")
                if len(data['transactions']) == 2:
                     self.stdout.write("   Found 2 expense records as expected")
                else:
                     self.stdout.write(self.style.ERROR(f"   Expected 2 expense records, found {len(data['transactions'])}"))
            else:
                 self.stdout.write(self.style.ERROR("   Missing expected keys in expense history response"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Expense History API failed: {response.status_code}"))

        # Cleanup
        user.delete()
        auction.delete()
        self.stdout.write("Cleanup completed")
