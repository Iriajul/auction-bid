from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.admin_api.models import Auction, AuctionStatus, Category
from apps.auction.models import Bid
from django.utils import timezone
from datetime import timedelta
import json

User = get_user_model()

class Command(BaseCommand):
    help = 'Verifies the User Bid History API'

    def handle(self, *args, **options):
        self.stdout.write("--- Verifying User Bid History API via Management Command ---")
        
        # 1. Setup User
        email = "history_test_cmd@example.com"
        user, _ = User.objects.get_or_create(email=email)
        user.set_password("password123")
        user.save()
        
        # 2. Setup Data
        cat, _ = Category.objects.get_or_create(name="HistoryTestCatCmd")
        
        # Auction 1: Active
        a1, _ = Auction.objects.get_or_create(
            id=9910, 
            defaults={
                'product_name': 'Test Drone Cmd',
                'auction_price': 100,
                'market_price': 500,
                'category': cat,
                'status': AuctionStatus.PUBLISH,
                'auction_duration': timedelta(minutes=60),
                'winning_claim_window': timedelta(hours=24)
            }
        )
        a1.status = AuctionStatus.PUBLISH
        a1.save()
        
        # Bid on A1
        Bid.objects.get_or_create(auction=a1, user=user, bid_number=1, defaults={'coins_deducted': 1})
        
        # Auction 2: Lost
        a2, _ = Auction.objects.get_or_create(
            id=9920,
            defaults={
                'product_name': 'Test Sofa Cmd', 
                'auction_price': 50,
                'market_price': 200,
                'category': cat,
                'status': AuctionStatus.ENDED,
                'auction_duration': timedelta(minutes=10),
                'winning_claim_window': timedelta(hours=24)
            }
        )
        Bid.objects.get_or_create(auction=a2, user=user, bid_number=1, defaults={'coins_deducted': 1})
        
        # 3. Get Token
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        
        # 4. Call API
        self.stdout.write("\n[GET] /api/auction/user-history/")
        response = client.get('/api/auction/user-history/')
        
        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ API Call Success"))
            data = response.data
            self.stdout.write(f"Items returned: {len(data)}")
            
            if len(data) > 0:
                item = data[0]
                self.stdout.write("\nResponse Item Structure:")
                self.stdout.write(json.dumps(item, indent=2, default=str))
                
                # Check specific values
                if item['currency'] == 'SAR':
                    self.stdout.write("✅ Currency is SAR")
                else:
                    self.stdout.write(self.style.ERROR(f"❌ Currency mismatch: {item['currency']}"))

                # Check deadline format (simple check)
                if item['deadline'] is None or 'T' in str(item['deadline']):
                     self.stdout.write("✅ Deadline is in valid format (ISO or None)")
                else:
                     self.stdout.write(self.style.ERROR(f"❌ Deadline format seems wrong: {item['deadline']}"))
                    
                # Verify keys
                required_keys = {'id', 'title', 'image', 'price', 'originalPrice', 'currency', 'bids', 'saves', 'time', 'description', 'status', 'deadline', 'current_bid_coin_count', 'joining_bid', 'coins_per_bid', 'total_spent'}
                keys = set(item.keys())
                
                if required_keys.issubset(keys):
                    self.stdout.write(self.style.SUCCESS("✅ JSON Structure matches requirements (including all fields)"))
                else:
                    self.stdout.write(self.style.ERROR(f"❌ Missing keys: {required_keys - keys}"))

                # Check new fields values specifically if item matches test setup
                if item['id'] == "9910":
                     if item['current_bid_coin_count'] == 1:
                         self.stdout.write("✅ current_bid_coin_count is correct (1)")
                     else:
                         self.stdout.write(self.style.ERROR(f"❌ current_bid_coin_count mismatch: {item['current_bid_coin_count']}"))
                     
                     if item['joining_bid'] == 0:
                         self.stdout.write("✅ joining_bid returned")

                     if item['coins_per_bid'] == 1:
                         self.stdout.write("✅ coins_per_bid is correct (1)")
                     else:
                         self.stdout.write(self.style.ERROR(f"❌ coins_per_bid mismatch: {item['coins_per_bid']}"))

                     if item['total_spent'] == 1: # joining_bid(0) + current_bid_coin_count(1)
                         self.stdout.write("✅ total_spent is correct (1)")
                     else:
                         self.stdout.write(self.style.ERROR(f"❌ total_spent mismatch: {item['total_spent']}"))
            else:
                self.stdout.write(self.style.WARNING("⚠️ No items returned"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ API Failed: {response.status_code}"))
            self.stdout.write(str(response.data))
