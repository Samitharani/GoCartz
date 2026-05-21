from django.shortcuts import render, redirect
from django.http import JsonResponse
from .models import Category, Product
from shop.form import CustomerUserForm
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from .models import Cart,Product,Favourite
from django.contrib.auth.decorators import login_required
from .models import UserProfile
from .forms import UserProfileForm

import json


def home(request):
    products = Product.objects.filter(trending=0)
    return render(request, 'shop/index.html', {"products": products})

@login_required
def profile_view(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return redirect('create_profile')

    return render(request, 'shop/profile.html', {'profile': profile})

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



def cart_page(request):
    cart_items = Cart.objects.all()  # 👈 ignore user filter
    return render(request, 'shop/cart.html', {'cart_items': cart_items})

def favviewpage(request):
    if request.user.is_authenticated:
        fav=Favourite.objects.filter(user=request.user)
        return render(request,"shop/fav.html",{"fav":fav})
    else:
        return redirect("/")


@login_required
def fav_page(request):
    pid = request.GET.get('pid')
    if not pid:
        return JsonResponse({'status': 'Missing product ID'}, status=400)

    try:
        product = Product.objects.get(id=pid)
    except Product.DoesNotExist:
        return JsonResponse({'status': 'Product not found'}, status=404)

    fav, created = Favourite.objects.get_or_create(user=request.user, product=product)

    if created:
        messages.success(request, "Added to favourites!")
    else:
        messages.info(request, "Already in favourites.")

    # Redirect user back to the same page they were on
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
    else:
        if request.method == 'POST':
            name = request.POST.get('username')
            pwd = request.POST.get('password')
            user = authenticate(request, username=name, password=pwd)
            if user is not None:
                login(request, user)
                messages.success(request, "Logged in successfully")
                return redirect("/")
            else:
                messages.error(request, "Invalid username or password")
                return redirect("/login")
        return render(request, 'shop/login.html')


def register(request):
    form = CustomerUserForm()
    if request.method == 'POST':
        form = CustomerUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Registration successful. You can login now!")
            return redirect('/login')
    return render(request, 'shop/register.html', {'form': form})


def collections(request):
    category = Category.objects.filter(status=0)
    return render(request, 'shop/collections.html', {"category": category})


def collectionsview(request, name):
    if Category.objects.filter(name=name, status=0).exists():
        products = Product.objects.filter(category__name=name)
        return render(request, 'shop/products/index.html', {"products": products, "category_name": name})
    else:
        messages.warning(request, "No such category found")
        return redirect('collections')


def product_details(request, cname, pname):
    if Category.objects.filter(name=cname, status=0).exists():
        if Product.objects.filter(name=pname, status=0).exists():
            products = Product.objects.filter(name=pname, status=0).first()
            return render(request, "shop/products/product_details.html", {"products": products})
        else:
            messages.error(request, "No such product found")
            return redirect('collections')
    else:
        messages.error(request, "No such category found")
        return redirect("collections")
