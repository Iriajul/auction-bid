import sys
import random
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.users.models import User

class Command(BaseCommand):
    help = 'Verify Admin User List API'

    def handle(self, *args, **options):
        # Create an admin user
        admin_email = "admin_verify@example.com"
        admin_user, created = User.objects.get_or_create(email=admin_email, defaults={"is_staff": True, "is_superuser": True})
        if not created:
             admin_user.is_staff = True
             admin_user.is_superuser = True
             admin_user.save()
        admin_user.set_password("password123")
        admin_user.save()

        # Create some test users
        User.objects.get_or_create(email="user1@example.com", defaults={"first_name": "User", "last_name": "One", "phone_number": "1234567890"})
        User.objects.get_or_create(email="user2@example.com", defaults={"first_name": "User", "last_name": "Two", "phone_number": "0987654321"})

        client = APIClient()
        client.force_authenticate(user=admin_user)

        self.stdout.write(f"Authenticated as admin: {admin_email}")

        # Test Admin User List API
        response = client.get('/api/admin/users/')
        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Admin User List API success"))
            # The result might be paginated or not, depending on the dynamic view
            data = response.data
            users = data.get('results', data) if isinstance(data, dict) else data
            self.stdout.write(f"   Found {len(users)} users (excluding superadmins likely)")
            for u in users:
                self.stdout.write(f"   - {u['email']} (Status: {u['status']}, Phone: {u['phone_number']})")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Admin User List API failed: {response.status_code}"))
            self.stdout.write(str(response.data))

        # Test Admin User Toggle Status API
        test_user = User.objects.get(email="user1@example.com")
        initial_status = test_user.is_active
        self.stdout.write(f"Testing toggle status for {test_user.email} (Current: {initial_status})")
        
        toggle_response = client.post('/api/admin/users/toggle-status/', {"user_id": test_user.id}, format='json')
        if toggle_response.status_code == 200:
            new_status = toggle_response.data['is_active']
            self.stdout.write(self.style.SUCCESS(f"✅ Admin User Toggle Status success (New status: {new_status})"))
            if new_status == initial_status:
                 self.stdout.write(self.style.ERROR("❌ Status did not actually change!"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Admin User Toggle Status failed: {toggle_response.status_code}"))
            self.stdout.write(str(toggle_response.data))

        # Test Admin User Auction History API
        history_response = client.get(f'/api/admin/users/history/?user_id={test_user.id}')
        if history_response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Admin User Auction History API success"))
            data = history_response.data
            history = data.get('results', data) if isinstance(data, dict) else data
            self.stdout.write(f"   Found {len(history)} history records")
            for h in history:
                self.stdout.write(f"   - Auction: {h['auction_title']}, Joined: {h['joined_at']}, Days Ago: {h['days_ago']}, Bids: {h['total_bids']}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Admin User Auction History API failed: {history_response.status_code}"))
            self.stdout.write(str(history_response.data))

        txn_response = client.get(f'/api/admin/users/transactions/?user_id={test_user.id}')
        if txn_response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Admin User Transaction History API success"))
            data = txn_response.data
            txns = data.get('results', data) if isinstance(data, dict) else data
            self.stdout.write(f"   Found {len(txns)} transaction records")
            for t in txns:
                self.stdout.write(f"   - Type: {t['transaction_type']}, Amount: {t['amount']}, Date: {t['created_at']}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Admin User Transaction History API failed: {txn_response.status_code}"))
            self.stdout.write(str(txn_response.data))

        # Test User Details API
        details_response = client.get(f'/api/admin/users/details/?user_id={test_user.id}')
        if details_response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("✅ Admin User Details API success"))
            self.stdout.write(f"   Coins: {details_response.data.get('wallet_coins')}, Refundable: {details_response.data.get('refundable_coins')}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Admin User Details API failed: {details_response.status_code}"))
            if hasattr(details_response, 'data'):
                self.stdout.write(str(details_response.data))
            else:
                self.stdout.write(str(details_response.content))

        # 6. Test Admin Profile Update API
        print(f"Testing profile update for admin")
        new_name = "Admin Updated"
        profile_response = client.patch('/api/admin/profile/update/', {"first_name": new_name}, format='json')
        if profile_response.status_code == 200:
            print(f"✅ Admin Profile Update success (New name: {profile_response.data.get('first_name')})")
        else:
            print(f"❌ Admin Profile Update failed: {profile_response.status_code}")
            print(profile_response.data)

        # 7. Test Admin Change Password API
        print(f"Testing password change for admin")
        # Note: We use password123 as set at the beginning of this script
        pwd_response = client.post('/api/admin/profile/change-password/', {
            "old_password": "password123",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123"
        }, format='json')
        if pwd_response.status_code == 200:
            print(f"✅ Admin Change Password success")
        else:
            print(f"❌ Admin Change Password failed: {pwd_response.status_code}")
            print(pwd_response.data)

        # 8. Test Admin Myself API
        print("Testing Admin Myself API")
        myself_response = client.get('/api/admin/profile/me/')
        if myself_response.status_code == 200:
            print(f"✅ Admin Myself GET success (Username: {myself_response.data.get('username')})")
            
            # Test PATCH
            new_username = f"admin_{random.randint(1000, 9999)}"
            new_first = "Admin"
            new_last = "User"
            print(f"Testing Admin Myself PATCH with username: {new_username}, name: {new_first} {new_last}")
            patch_data = {
                "username": new_username,
                "first_name": new_first,
                "last_name": new_last
            }
            patch_response = client.patch('/api/admin/profile/me/', patch_data, format='json')
            if patch_response.status_code == 200:
                print(f"✅ Admin Myself PATCH success")
                print(f"   New username: {patch_response.data.get('username')}")
                print(f"   First Name: {patch_response.data.get('first_name')}")
                print(f"   Last Name: {patch_response.data.get('last_name')}")
            else:
                print(f"❌ Admin Myself PATCH failed: {patch_response.status_code}")
                print(patch_response.data)
        else:
            print(f"❌ Admin Myself GET failed: {myself_response.status_code}")
            print(myself_response.data)

        # 9. Test Admin Coin Stats API
        print("Testing Coin Stats API")
        stats_response = client.get('/api/admin/coin-stats/')
        if stats_response.status_code == 200:
            print(f"✅ Admin Coin Stats success")
            print(f"   Sold: {stats_response.data.get('solds_coins')} (SAR: {stats_response.data.get('saudi_rial_sold_coins')})")
            print(f"   Unused: {stats_response.data.get('unused_coins')} (SAR: {stats_response.data.get('saudi_rial_unused_coins')})")
            print(f"   Refundable: {stats_response.data.get('refundable_coins')} (SAR: {stats_response.data.get('saudi_rial_refundable_coins')})")
            print(f"   Non-Refundable: {stats_response.data.get('non_refundable_coins')} (SAR: {stats_response.data.get('saudi_rial_non_refundable_coins')})")
        else:
            print(f"❌ Admin Coin Stats failed: {stats_response.status_code}")
            print(stats_response.data)

        self.stdout.write("Verification completed")
