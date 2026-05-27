from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User
from django.db.models import Sum, Q, Count, Case, When, IntegerField
from django.utils import timezone
from datetime import timedelta
from .models import Category, CommissionSetting, Product, Cart, Favourite, UserProfile, Address, Order, OrderItem, Review
from shop.form import CustomerUserForm
from .forms import UserProfileForm, ProductForm, AddressForm, CategoryForm

import json
from django.conf import settings
import razorpay
from razorpay.errors import BadRequestError, SignatureVerificationError
import logging
logger = logging.getLogger(__name__)



def home(request):
    products = Product.objects.filter(trending=0)
    return render(request, 'shop/index.html', {"products": products})

@login_required
def profile_view(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return redirect('create_profile')

    addresses = profile.addresses.all()
    return render(request, 'shop/profile.html', {'profile': profile, 'addresses': addresses})

@login_required
def edit_profile(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return redirect('create_profile')

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile')
    else:
        form = UserProfileForm(instance=profile)

    return render(request, 'shop/create_profile.html', {'form': form, 'edit_mode': True})


@login_required
def add_address(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, 'Please complete your profile before adding an address.')
        return redirect('create_profile')

    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user_profile = profile
            address.save()
            messages.success(request, 'Address added successfully.')
            return redirect('profile')
    else:
        form = AddressForm()

    return render(request, 'shop/add_address.html', {'form': form})

@login_required
def create_profile(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.save()
            return redirect('profile')
    else:
        form = UserProfileForm()

    return render(request, 'shop/create_profile.html', {'form': form})



@login_required
def cart_page(request):
    cart_items = Cart.objects.filter(user=request.user)
    total_amount = sum(item.total_cost for item in cart_items)
    return render(request, 'shop/cart.html', {'cart_items': cart_items, 'total_amount': total_amount})

@login_required
@ensure_csrf_cookie
def checkout(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, 'Please complete your profile before checking out.')
        return redirect('create_profile')

    cart_items = Cart.objects.filter(user=request.user)
    if not cart_items.exists():
        messages.info(request, 'Your cart is empty. Add some products before checking out.')
        return redirect('cart_page')

    addresses = Address.objects.filter(user_profile=profile)
    total_amount = sum(item.total_cost for item in cart_items)

    if request.method == 'POST':
        address_id = request.POST.get('selected_address')
        if not address_id:
            messages.error(request, 'Please select a delivery address before placing the order.')
            return redirect('checkout')

        try:
            shipping_address = addresses.get(id=address_id)
        except Address.DoesNotExist:
            messages.error(request, 'Selected address is not valid.')
            return redirect('checkout')

        if settings.RAZORPAY_KEY_ID in ('rzp_test_your_key_here', '') or settings.RAZORPAY_KEY_SECRET in ('rzp_test_secret_here', ''):
            messages.error(request, 'Razorpay API keys are not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in environment variables or settings.')
            return redirect('checkout')

        # Create order in our DB with pending payment
        order = Order.objects.create(
            user=request.user,
            address=shipping_address,
            total_price=total_amount,
            payment_method='Razorpay',
            status='Placed',
            payment_status='Pending'
        )

        for item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.product_qty,
                price=item.product.selling_price,
                subtotal=item.total_cost,
            )

        # Prepare Razorpay order
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        try:
            razorpay_order = client.order.create(dict(amount=int(total_amount * 100),
                                                      currency='INR',
                                                      receipt=f'order_{order.id}',
                                                      payment_capture='1'))
        except BadRequestError:
            order.delete()
            messages.error(request, 'Payment gateway authentication failed. Please verify your Razorpay key and secret.')
            return redirect('checkout')
        except Exception:
            order.delete()
            messages.error(request, 'Unable to create a payment order. Please try again later.')
            return redirect('checkout')

        order.razorpay_order_id = razorpay_order.get('id')
        order.save()

        # Render a lightweight payment page which will open Razorpay Checkout
        return render(request, 'shop/payment.html', {
            'order': order,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'razorpay_order': razorpay_order,
            'total_amount': int(total_amount),
        })

    return render(request, 'shop/checkout.html', {
        'cart_items': cart_items,
        'addresses': addresses,
        'total_amount': total_amount,
    })


@login_required
def payment_verify(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    data = request.POST
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    order_id = data.get('order_id')

    try:
        order = Order.objects.get(id=order_id, razorpay_order_id=razorpay_order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        client.utility.verify_payment_signature(params_dict)
    except SignatureVerificationError as e:
        logger.error('Razorpay signature verification failed for order %s: %s', order_id, str(e))
        order.payment_status = 'Failed'
        order.save()
        return JsonResponse({'success': False, 'error': 'Signature verification failed', 'detail': str(e)})
    except BadRequestError as e:
        logger.error('Razorpay BadRequest for order %s: %s', order_id, str(e))
        order.payment_status = 'Failed'
        order.save()
        return JsonResponse({'success': False, 'error': 'Payment gateway error', 'detail': str(e)})
    except Exception as e:
        logger.exception('Unexpected error verifying payment for order %s', order_id)
        order.payment_status = 'Failed'
        order.save()
        return JsonResponse({'success': False, 'error': 'Signature verification failed', 'detail': str(e)})

    # Mark payment as successful
    order.payment_id = razorpay_payment_id
    order.payment_method = 'Razorpay'
    order.payment_status = 'Paid'
    order.status = 'Processing'
    order.save()

    # reduce product quantities and clear cart for the user
    cart_items = Cart.objects.filter(user=request.user)
    for item in cart_items:
        if item.product and item.product.quantity >= item.product_qty:
            item.product.quantity -= item.product_qty
            item.product.save()
    cart_items.delete()

    return JsonResponse({'success': True, 'order_id': order.id})


@login_required
def orders_page(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'shop/orders.html', {'orders': orders})

@login_required
def favviewpage(request):
    fav = Favourite.objects.filter(user=request.user)
    return render(request, "shop/fav.html", {"fav": fav})


@login_required
def fav_page(request):
    pid = None
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            pid = data.get('pid')
        except Exception:
            pid = request.POST.get('pid')
    else:
        pid = request.GET.get('pid')

    if not pid:
        return JsonResponse({'status': 'Missing product ID'}, status=400)

    try:
        product = Product.objects.get(id=pid)
    except Product.DoesNotExist:
        return JsonResponse({'status': 'Product not found'}, status=404)

    fav, created = Favourite.objects.get_or_create(user=request.user, product=product)

    if request.method == 'POST':
        if created:
            return JsonResponse({'status': 'Added to favourites!'}, status=200)
        return JsonResponse({'status': 'Already in favourites.'}, status=200)

    if created:
        messages.success(request, "Added to favourites!")
    else:
        messages.info(request, "Already in favourites.")

    return redirect(request.META.get('HTTP_REFERER', 'favviewpage'))




def add_to_cart(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            pid = data.get("pid")
            qty = data.get("product_qty")

            product = Product.objects.get(id=pid)

            if not product.is_active:
                return JsonResponse({'status': 'Product is inactive'}, status=400)

            if product.quantity < int(qty):
                return JsonResponse({'status': 'Not enough stock'}, status=400)

            # ✅ Save to cart
            Cart.objects.create(
                user=request.user,
                product=product,
                product_qty=qty
            )

            return JsonResponse({'status': 'Product Added to Cart'}, status=200)

        except Product.DoesNotExist:
            return JsonResponse({'status': 'Product not found'}, status=404)
        except Exception as e:
            return JsonResponse({'status': str(e)}, status=500)

    return JsonResponse({'status': 'Invalid request'}, status=400)

def remove_page(request,cid):
    cartitem=Cart.objects.get(id=cid)
    cartitem.delete()
    return redirect('/cart')

def remove_fav(request,fid):
    item=Favourite.objects.get(id=fid)
    item.delete()
    return redirect('/favviewpage')

    
def logout_page(request):
    if request.user.is_authenticated:
        logout(request)
        messages.success(request, "Logged out successfully")
    return redirect("/")


def login_page(request):
    if request.user.is_authenticated:
        return redirect("/")

    selected_role = request.POST.get('role') if request.method == 'POST' else request.GET.get('role', 'buyer')
    if selected_role not in ['buyer', 'seller', 'admin']:
        selected_role = 'buyer'

    if request.method == 'POST':
        username = request.POST.get('username')
        pwd = request.POST.get('password')
        user = authenticate(request, username=username, password=pwd)

        if user is not None:
            profile = None
            try:
                profile = user.userprofile
            except UserProfile.DoesNotExist:
                profile = None

            if selected_role == 'admin':
                if not (user.is_staff or user.is_superuser):
                    messages.error(request, "Admin login is only for platform administrators.")
                    return render(request, 'shop/login.html', {'selected_role': selected_role})
            elif selected_role == 'seller':
                if not profile or profile.role != 'seller':
                    messages.error(request, "Please login with a seller account.")
                    return render(request, 'shop/login.html', {'selected_role': selected_role})
                if not profile.is_vendor_approved:
                    messages.error(request, "Your seller account is pending approval.")
                    return render(request, 'shop/login.html', {'selected_role': selected_role})
            else:
                if profile and profile.role != 'buyer':
                    messages.error(request, "Use the seller login if you registered as a vendor.")
                    return render(request, 'shop/login.html', {'selected_role': selected_role})

            login(request, user)
            messages.success(request, "Logged in successfully")
            if selected_role == 'admin':
                return redirect('/admin/')
            if selected_role == 'seller':
                return redirect('seller_dashboard')
            return redirect("/")

        messages.error(request, "Invalid username or password")

    return render(request, 'shop/login.html', {'selected_role': selected_role})


def register(request):
    selected_role = request.GET.get('role', request.POST.get('role', 'buyer'))
    # Only allow buyer and seller registration, admin cannot be registered
    if selected_role not in ['buyer', 'seller']:
        selected_role = 'buyer'

    form = CustomerUserForm(request.POST or None)

    if request.method == 'POST':
        seller_required = ['shop_name', 'business_category', 'city'] if selected_role == 'seller' else []
        missing = [field for field in seller_required if not request.POST.get(field)]

        if missing:
            for field in missing:
                if field == 'shop_name':
                    messages.error(request, 'Shop name is required for vendor registration.')
                elif field == 'business_category':
                    messages.error(request, 'Business category is required for vendor registration.')
                elif field == 'city':
                    messages.error(request, 'City is required for vendor registration.')
        elif form.is_valid():
            user = form.save()
            UserProfile.objects.create(
                user=user,
                phone=request.POST.get('phone', ''),
                role=selected_role,
                vendor_name=request.POST.get('shop_name', '') if selected_role == 'seller' else '',
                business_category=request.POST.get('business_category', '') if selected_role == 'seller' else '',
                vendor_city=request.POST.get('city', '') if selected_role == 'seller' else '',
                gst_number=request.POST.get('gst_number', '') if selected_role == 'seller' else '',
                description=request.POST.get('description', '') if selected_role == 'seller' else '',
                is_vendor=(selected_role == 'seller'),
                is_vendor_approved=(selected_role != 'seller'),
                vendor_request_status='pending' if selected_role == 'seller' else 'approved',
            )
            if selected_role == 'buyer':
                messages.success(request, "Buyer registered successfully. Please login to continue.")
            else:
                messages.success(request, "Vendor registered successfully. Please login to continue.")
            next_login = '/login?role=seller' if selected_role == 'seller' else '/login?role=buyer'
            return redirect(next_login)
        else:
            messages.error(request, "Please fix the errors and try again.")

    return render(request, 'shop/register.html', {'form': form, 'selected_role': selected_role})


def collections(request):
    category = Category.objects.filter(status=0)
    return render(request, 'shop/collections.html', {"category": category})


@login_required
def seller_dashboard(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before accessing the seller dashboard.")
        return redirect('create_profile')

    if profile.role != 'seller':
        messages.error(request, "Seller dashboard is only available to seller accounts.")
        return redirect('home')

    if not profile.is_vendor_approved:
        messages.error(request, "Your seller account is not approved yet.")
        return redirect('/login?role=seller')

    non_cancelled_statuses = ['Placed', 'Processing', 'Shipped', 'Delivered']
    products = Product.objects.filter(vendor=request.user.username).annotate(
        units_sold=Sum(
            'orderitem__quantity',
            filter=Q(orderitem__order__status__in=non_cancelled_statuses)
        )
    ).order_by('-units_sold')

    product_count = products.count()
    active_products = products.filter(is_active=True).count()
    low_stock_products = products.filter(quantity__lte=5).order_by('quantity')
    low_stock_count = low_stock_products.count()

    total_revenue = OrderItem.objects.filter(
        product__vendor=request.user.username,
        order__status__in=non_cancelled_statuses
    ).aggregate(total=Sum('subtotal'))['total'] or 0

    commission_amount = round(total_revenue * 0.10, 2)
    after_commission = round(total_revenue - commission_amount, 2)

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)
    previous_week_start = week_start - timedelta(days=7)

    weekly_orders = Order.objects.filter(
        items__product__vendor=request.user.username,
        created_at__gte=week_start,
        status__in=non_cancelled_statuses
    ).distinct().count()

    previous_week_orders = Order.objects.filter(
        items__product__vendor=request.user.username,
        created_at__gte=previous_week_start,
        created_at__lt=week_start,
        status__in=non_cancelled_statuses
    ).distinct().count()

    orders_today = Order.objects.filter(
        items__product__vendor=request.user.username,
        created_at__gte=today_start,
        status__in=non_cancelled_statuses
    ).distinct().count()

    pending_orders = OrderItem.objects.filter(
        product__vendor=request.user.username,
        order__status='Placed'
    ).values('order').distinct().count()

    revenue_growth = 0
    if previous_week_orders > 0:
        revenue_growth = round(((weekly_orders - previous_week_orders) / previous_week_orders) * 100, 1)

    return render(request, 'shop/seller/dashboard.html', {
        'products': products,
        'product_count': product_count,
        'active_products': active_products,
        'low_stock_count': low_stock_count,
        'pending_orders': pending_orders,
        'low_stock_products': low_stock_products,
        'total_revenue': round(total_revenue, 2),
        'revenue_growth': revenue_growth,
        'weekly_orders': weekly_orders,
        'orders_today': orders_today,
        'after_commission': after_commission,
        'commission_amount': commission_amount,
        'profile': profile,
        'seller_active': 'dashboard',
    })


@login_required
def seller_add_product(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before adding products.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can add products.")
        return redirect('home')

    categories = Category.objects.filter(status=0)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.vendor = request.user.username
            product.save()
            messages.success(request, 'Product added successfully. Buyers can now view it.')
            return redirect('seller_products')
        else:
            messages.error(request, 'Please fix the highlighted errors before saving your product.')
    else:
        form = ProductForm()

    return render(request, 'shop/seller/add_product.html', {
        'form': form,
        'profile': profile,
        'seller_active': 'add_product',
        'categories': categories,
        'pending_orders': 0,
        'low_stock_count': 0,
    })


@login_required
def get_smart_price(request):
    """API endpoint to get smart price suggestion based on category"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        category_id = request.POST.get('category_id')
        
        if not category_id:
            return JsonResponse({
                'error': 'Category ID required',
                'min_price': None,
                'max_price': None,
                'similar_count': 0
            })
        
        # Get similar products from the same category
        similar_products = Product.objects.filter(
            category_id=category_id,
            is_active=True,
            status=False  # 0-show, 1-hidden
        ).values_list('selling_price', flat=True)
        
        if similar_products.count() > 0:
            prices = list(similar_products)
            min_price = int(min(prices) * 0.9)  # 10% lower
            max_price = int(max(prices) * 1.1)  # 10% higher
            avg_price = int(sum(prices) / len(prices))
            
            return JsonResponse({
                'min_price': min_price,
                'max_price': max_price,
                'avg_price': avg_price,
                'similar_count': similar_products.count(),
                'success': True
            })
        else:
            return JsonResponse({
                'error': 'No similar products found',
                'min_price': None,
                'max_price': None,
                'similar_count': 0,
                'success': False
            })
    
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'min_price': None,
            'max_price': None,
            'similar_count': 0
        })


@login_required
def seller_products(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before viewing your products.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can view this page.")
        return redirect('home')

    products = Product.objects.filter(vendor=request.user.username)
    low_stock_count = products.filter(quantity__lte=5).count()
    pending_orders = OrderItem.objects.filter(product__vendor=request.user.username, order__status='Placed').count()

    return render(request, 'shop/seller/products.html', {
        'products': products,
        'profile': profile,
        'seller_active': 'products',
        'pending_orders': pending_orders,
        'low_stock_count': low_stock_count,
    })


@login_required
def seller_edit_product(request, product_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before editing products.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can edit products.")
        return redirect('home')

    product = Product.objects.filter(id=product_id, vendor=request.user.username).first()
    if not product:
        messages.error(request, 'Product not found.')
        return redirect('seller_products')

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully.')
            return redirect('seller_products')
        else:
            messages.error(request, 'Please fix the errors before updating the product.')
    else:
        form = ProductForm(instance=product)

    products = Product.objects.filter(vendor=request.user.username)
    low_stock_count = products.filter(quantity__lte=5).count()
    pending_orders = OrderItem.objects.filter(product__vendor=request.user.username, order__status='Placed').count()

    categories = []
    if hasattr(form, 'fields') and 'category' in form.fields:
        categories = form.fields['category'].queryset

    return render(request, 'shop/seller/add_product.html', {
        'form': form,
        'product': product,
        'profile': profile,
        'seller_active': 'add_product',
        'categories': categories,
        'pending_orders': pending_orders,
        'low_stock_count': low_stock_count,
        'edit_mode': True,
    })


@login_required
def seller_delete_product(request, product_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before deleting products.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can delete products.")
        return redirect('home')

    product = Product.objects.filter(id=product_id, vendor=request.user.username).first()
    if not product:
        messages.error(request, 'Product not found.')
    else:
        product.delete()
        messages.success(request, 'Product deleted successfully.')

    return redirect('seller_products')


@login_required
def seller_restock_product(request, product_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before restocking products.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can restock products.")
        return redirect('home')

    product = Product.objects.filter(id=product_id, vendor=request.user.username).first()
    if not product:
        messages.error(request, 'Product not found.')
        return redirect('seller_low_stock')

    if request.method == 'POST':
        try:
            qty = int(request.POST.get('restock_qty', product.quantity))
            product.quantity = max(qty, 0)
            product.save()
            messages.success(request, 'Product restocked successfully.')
        except ValueError:
            messages.error(request, 'Invalid quantity value.')

    return redirect('seller_low_stock')


@login_required
def seller_orders(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before viewing orders.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can view this page.")
        return redirect('home')

    products = Product.objects.filter(vendor=request.user.username)
    low_stock_count = products.filter(quantity__lte=5).count()
    pending_orders = OrderItem.objects.filter(product__vendor=request.user.username, order__status='Placed').count()

    order_items = OrderItem.objects.filter(product__vendor=request.user.username).select_related('order', 'product', 'order__user').order_by('-order__created_at')
    orders = []
    for item in order_items:
        orders.append({
            'id': item.order.id,
            'display_id': f"ORD-{item.order.id:04d}",
            'product': item.product.name if item.product else 'Unknown Product',
            'buyer': item.order.user.username,
            'qty': item.quantity,
            'amount': item.subtotal,
            'date': item.order.created_at.strftime('%d %b %Y'),
            'status': item.order.status,
        })

    placed_count = sum(1 for order in orders if order['status'] == 'Placed')
    confirmed_count = sum(1 for order in orders if order['status'] == 'Processing')
    shipped_count = sum(1 for order in orders if order['status'] == 'Shipped')
    delivered_count = sum(1 for order in orders if order['status'] == 'Delivered')

    status_filter = request.GET.get('status')
    if status_filter and status_filter != 'all':
        orders = [order for order in orders if order['status'] == status_filter]

    return render(request, 'shop/seller/orders.html', {
        'profile': profile,
        'orders': orders,
        'seller_active': 'orders',
        'pending_orders': pending_orders,
        'low_stock_count': low_stock_count,
        'placed_count': placed_count,
        'confirmed_count': confirmed_count,
        'shipped_count': shipped_count,
        'delivered_count': delivered_count,
    })


@login_required
def seller_confirm_order(request, order_id):
    try:
        order = Order.objects.filter(items__product__vendor=request.user.username, id=order_id).distinct().get()
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('seller_orders')

    if request.method == 'POST':
        if order.status == 'Placed':
            order.status = 'Processing'
            order.save()
            messages.success(request, 'Order confirmed successfully.')
        else:
            messages.info(request, 'Only placed orders can be confirmed.')

    return redirect('seller_orders')


@login_required
def seller_ship_order(request, order_id):
    try:
        order = Order.objects.filter(items__product__vendor=request.user.username, id=order_id).distinct().get()
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('seller_orders')

    if request.method == 'POST':
        if order.status == 'Processing':
            order.status = 'Shipped'
            order.save()
            messages.success(request, 'Order marked as shipped.')
        else:
            messages.info(request, 'Only confirmed orders can be marked shipped.')

    return redirect('seller_orders')


@login_required
def seller_earnings(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before viewing earnings.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can view this page.")
        return redirect('home')

    products = Product.objects.filter(vendor=request.user.username)
    low_stock_count = products.filter(quantity__lte=5).count()
    pending_orders = OrderItem.objects.filter(product__vendor=request.user.username, order__status='Placed').count()
    # Compute real earnings for this seller from OrderItems
    commission_setting = CommissionSetting.objects.first()
    commission_rate = commission_setting.rate if commission_setting else 10.0

    total_qs = OrderItem.objects.filter(product__vendor=request.user.username, order__payment_status='Paid')
    total_earned = int(total_qs.aggregate(total=Sum('subtotal'))['total'] or 0)
    commission_amount = int(round(total_earned * (commission_rate / 100.0)))
    net_earnings = int(total_earned - commission_amount)

    # Build a simple 3-week history (last 3 seven-day periods)
    history = []
    today = timezone.localdate()
    for i in range(3):
        end = today - timedelta(days=7 * i)
        start = end - timedelta(days=6)
        week_label = f"{start.strftime('%b %d')}–{end.strftime('%b %d')}"

        week_qs = OrderItem.objects.filter(
            product__vendor=request.user.username,
            order__created_at__date__range=(start, end)
        )
        gross = int(week_qs.aggregate(total=Sum('subtotal'))['total'] or 0)
        orders_count = week_qs.values('order').distinct().count()
        week_comm = int(round(gross * (commission_rate / 100.0)))
        week_net = int(gross - week_comm)

        # Status: Paid if all related orders in range are paid
        related_orders = Order.objects.filter(
            id__in=week_qs.values_list('order', flat=True).distinct()
        )
        if related_orders.exists() and all(o.payment_status == 'Paid' for o in related_orders):
            status = 'Paid'
        elif related_orders.exists():
            status = 'Pending'
        else:
            status = 'Pending'

        history.append({'week': week_label, 'orders': orders_count, 'gross': gross, 'commission': week_comm, 'net': week_net, 'status': status})

    earnings = {
        'total_earned': total_earned,
        'commission': commission_amount,
        'net_earnings': net_earnings,
        'history': history,
    }

    return render(request, 'shop/seller/earnings.html', {
        'profile': profile,
        'earnings': earnings,
        'seller_active': 'earnings',
        'pending_orders': pending_orders,
        'low_stock_count': low_stock_count,
    })


@login_required
def seller_low_stock(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Please complete your profile before viewing low stock.")
        return redirect('create_profile')

    if profile.role != 'seller' or not profile.is_vendor_approved:
        messages.error(request, "Only approved sellers can view this page.")
        return redirect('home')

    products = Product.objects.filter(vendor=request.user.username, quantity__lte=5)
    return render(request, 'shop/seller/low_stock.html', {
        'profile': profile,
        'products': products,
        'seller_active': 'low_stock',
    })


@login_required
def admin_dashboard(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    total_sales = Order.objects.aggregate(total=Sum('total_price'))['total'] or 0
    total_orders = Order.objects.count()
    active_vendors = UserProfile.objects.filter(role='seller', is_vendor_approved=True).count()
    pending_approvals = UserProfile.objects.filter(role='seller', is_vendor_approved=False).count()
    refund_requests = Order.objects.filter(status='Cancelled').count()
    commission_setting = CommissionSetting.objects.first()
    commission_rate = commission_setting.rate / 100 if commission_setting else 0.10
    commission_earned = round(total_sales * commission_rate)

    top_vendors_qs = Product.objects.filter(orderitem__isnull=False).values('vendor').annotate(
        total_sales=Sum('orderitem__subtotal'),
        orders=Count('orderitem__order', distinct=True)
    ).order_by('-total_sales')[:5]

    top_vendors = []
    for vendor_data in top_vendors_qs:
        vendor_username = vendor_data['vendor']
        profile = UserProfile.objects.filter(user__username=vendor_username).first()
        top_vendors.append({
            'vendor_name': profile.vendor_name if profile else vendor_username,
            'business_category': profile.business_category if profile else 'N/A',
            'vendor_city': profile.vendor_city if profile else 'N/A',
            'total_sales': int(vendor_data['total_sales'] or 0),
            'orders': int(vendor_data['orders'] or 0),
            'is_vendor_approved': profile.is_vendor_approved if profile else False,
        })

    if not top_vendors:
        approved_vendors = UserProfile.objects.filter(role='seller').order_by('-is_vendor_approved', 'vendor_name')[:5]
        for profile in approved_vendors:
            top_vendors.append({
                'vendor_name': profile.vendor_name or profile.user.username,
                'business_category': profile.business_category or 'N/A',
                'vendor_city': profile.vendor_city or 'N/A',
                'total_sales': 0,
                'orders': 0,
                'is_vendor_approved': profile.is_vendor_approved,
            })

    return render(request, 'shop/admin/dashboard.html', {
        'total_sales': int(total_sales),
        'active_vendors': active_vendors,
        'total_orders': total_orders,
        'commission_earned': commission_earned,
        'pending_approvals': pending_approvals,
        'refund_requests': refund_requests,
        'top_vendors': top_vendors,
        'admin_active': 'dashboard',
    })


@login_required
def admin_vendor_approvals(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    seller_requests = UserProfile.objects.filter(role='seller', is_vendor=True).annotate(
        status_order=Case(
            When(vendor_request_status='pending', then=0),
            When(vendor_request_status='approved', then=1),
            When(vendor_request_status='rejected', then=2),
            default=3,
            output_field=IntegerField(),
        )
    ).order_by('status_order', 'vendor_name')
    return render(request, 'shop/admin/vendor_approvals.html', {
        'seller_requests': seller_requests,
        'admin_active': 'vendor_approvals',
    })


@login_required
def admin_vendor_action(request, seller_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    seller_profile = UserProfile.objects.filter(id=seller_id, role='seller').first()
    if not seller_profile:
        messages.error(request, "Vendor profile not found.")
        return redirect('admin_vendor_approvals')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            seller_profile.is_vendor = True
            seller_profile.is_vendor_approved = True
            seller_profile.vendor_request_status = 'approved'
            seller_profile.save()
            messages.success(request, f"Vendor {seller_profile.vendor_name or seller_profile.user.username} approved.")
        elif action == 'reject':
            seller_profile.is_vendor = True
            seller_profile.is_vendor_approved = False
            seller_profile.vendor_request_status = 'rejected'
            seller_profile.save()
            messages.success(request, f"Vendor {seller_profile.vendor_name or seller_profile.user.username} has been rejected.")
        else:
            messages.error(request, "Invalid action.")

    return redirect('admin_vendor_approvals')


@login_required
def admin_categories(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    form = CategoryForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        if form.is_valid():
            category = form.save(commit=False)
            category.status = form.cleaned_data.get('status')
            category.save()
            messages.success(request, "Category added successfully.")
            return redirect('admin_categories')
        else:
            messages.error(request, "Please fix the errors in the category form.")

    categories = Category.objects.annotate(product_count=Count('product')).order_by('-created_at')
    return render(request, 'shop/admin/categories.html', {
        'categories': categories,
        'form': form,
        'admin_active': 'categories',
    })


@login_required
def admin_all_orders(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    orders = Order.objects.select_related('user').prefetch_related('items__product').order_by('-created_at')
    return render(request, 'shop/admin/orders.html', {
        'orders': orders,
        'admin_active': 'all_orders',
    })


@login_required
def admin_commission_settings(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    commission, _ = CommissionSetting.objects.get_or_create(pk=1, defaults={'rate': 10.0})

    if request.method == 'POST':
        try:
            rate = float(request.POST.get('commission_rate', commission.rate))
        except (TypeError, ValueError):
            rate = commission.rate

        rate = max(0.0, min(100.0, rate))
        commission.rate = rate
        commission.save()
        messages.success(request, f"Commission updated to {commission.rate}%.")
        return redirect('admin_commission_settings')

    return render(request, 'shop/admin/commission_settings.html', {
        'commission': commission,
        'admin_active': 'commission',
    })


@login_required
def admin_refund_requests(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    refund_requests = Order.objects.filter(status='Cancelled').select_related('user').order_by('-updated_at')
    return render(request, 'shop/admin/refund_requests.html', {
        'refund_requests': refund_requests,
        'admin_active': 'refunds',
    })


@login_required
def admin_analytics(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Admin access is restricted.")
        return redirect('login')

    now = timezone.now()
    current_year = now.year
    non_cancelled_statuses = ['Placed', 'Processing', 'Shipped', 'Delivered']

    monthly_revenue = Order.objects.filter(
        created_at__year=current_year,
        created_at__month=now.month,
        status__in=non_cancelled_statuses
    ).aggregate(total=Sum('total_price'))['total'] or 0

    active_sellers = UserProfile.objects.filter(role='seller', is_vendor_approved=True).count()
    pending_vendors = UserProfile.objects.filter(role='seller', is_vendor_approved=False).count()

    sales_trend = []
    for month in range(1, 6):
        month_revenue = Order.objects.filter(
            created_at__year=current_year,
            created_at__month=month,
            status__in=non_cancelled_statuses
        ).aggregate(total=Sum('total_price'))['total'] or 0
        sales_trend.append({
            'month': now.replace(month=month).strftime('%b'),
            'sales': int(month_revenue),
        })

    top_categories = Category.objects.annotate(
        sales=Sum('product__orderitem__subtotal', filter=Q(product__orderitem__order__status__in=non_cancelled_statuses), default=0),
        product_count=Count('product', distinct=True)
    ).order_by('-sales')[:6]
    
    # If no categories with sales, include categories with products
    if not top_categories or all(cat.sales == 0 for cat in top_categories):
        top_categories = Category.objects.annotate(
            sales=Sum('product__orderitem__subtotal', filter=Q(product__orderitem__order__status__in=non_cancelled_statuses), default=0),
            product_count=Count('product', distinct=True)
        ).filter(product_count__gt=0).order_by('name')[:6]

    top_vendors = []
    vendor_qs = Product.objects.filter(
        orderitem__order__status__in=non_cancelled_statuses
    ).values('vendor').annotate(
        total_sales=Sum('orderitem__subtotal'),
        orders=Count('orderitem__order', distinct=True)
    ).order_by('-total_sales')[:5]

    for item in vendor_qs:
        vendor_name = item['vendor']
        profile = UserProfile.objects.filter(user__username=vendor_name).first()
        top_vendors.append({
            'vendor_name': profile.vendor_name if profile and profile.vendor_name else vendor_name,
            'total_sales': int(item['total_sales'] or 0),
            'orders': int(item['orders'] or 0),
        })

    analytics = {
        'year': current_year,
        'monthly_revenue': int(monthly_revenue),
        'active_sellers': active_sellers,
        'pending_vendors': pending_vendors,
        'sales_trend': sales_trend,
        'top_categories': top_categories,
        'top_vendors': top_vendors,
    }

    return render(request, 'shop/admin/analytics.html', {
        'analytics': analytics,
        'admin_active': 'analytics',
    })


def collectionsview(request, name):
    if Category.objects.filter(name=name, status=0).exists():
        products = Product.objects.filter(category__name=name, status=0)
        vendor_locations = UserProfile.objects.filter(
            role='seller',
            user__username__in=products.values_list('vendor', flat=True)
        ).exclude(vendor_city='').values_list('vendor_city', flat=True).distinct()

        min_price = request.GET.get('min_price')
        max_price = request.GET.get('max_price')
        vendor_city = request.GET.get('vendor_city')

        if min_price:
            try:
                products = products.filter(selling_price__gte=float(min_price))
            except ValueError:
                pass

        if max_price:
            try:
                products = products.filter(selling_price__lte=float(max_price))
            except ValueError:
                pass

        if vendor_city:
            vendor_usernames = UserProfile.objects.filter(
                vendor_city__iexact=vendor_city,
                role='seller'
            ).values_list('user__username', flat=True)
            products = products.filter(vendor__in=vendor_usernames)

        return render(request, 'shop/products/index.html', {
            "products": products,
            "category_name": name,
            "vendor_locations": vendor_locations,
            "selected_min_price": min_price or '',
            "selected_max_price": max_price or '',
            "selected_vendor_city": vendor_city or '',
        })
    else:
        messages.warning(request, "No such category found")
        return redirect('collections')


def product_details(request, cname, pname):
    if Category.objects.filter(name=cname, status=0).exists():
        if Product.objects.filter(name=pname, status=0).exists():
            product = Product.objects.filter(name=pname, status=0).first()
            if request.method == 'POST':
                if not request.user.is_authenticated:
                    messages.error(request, 'Please log in to submit a review.')
                    return redirect('login')

                rating = request.POST.get('rating')
                comment = request.POST.get('comment', '').strip()

                try:
                    rating_value = int(rating)
                except (TypeError, ValueError):
                    rating_value = 5

                if rating_value < 1:
                    rating_value = 1
                elif rating_value > 5:
                    rating_value = 5

                Review.objects.create(
                    product=product,
                    user=request.user,
                    rating=rating_value,
                    comment=comment,
                )
                messages.success(request, 'Thank you! Your review has been submitted.')
                return redirect(request.path)

            return render(request, "shop/products/product_details.html", {"products": product})
        else:
            messages.error(request, "No such product found")
            return redirect('collections')
    else:
        messages.error(request, "No such category found")
        return redirect("collections")
