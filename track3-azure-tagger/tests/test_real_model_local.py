from tagging.real_pipeline import tag_local_image

image_path = "tmp/current_image.jpg"

tags = tag_local_image(image_path)

print("Final tags:")
print(tags)
